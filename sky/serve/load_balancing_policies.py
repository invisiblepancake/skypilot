"""LoadBalancingPolicy: Policy to select endpoint."""
import asyncio
import collections
import random
import threading
import typing
from typing import Any, Dict, List, Optional

import aiohttp

from sky import sky_logging

if typing.TYPE_CHECKING:
    import fastapi

logger = sky_logging.init_logger(__name__)

# Define a registry for load balancing policies
LB_POLICIES = {}
DEFAULT_LB_POLICY = None


def _request_repr(request: 'fastapi.Request') -> str:
    return ('<Request '
            f'method="{request.method}" '
            f'url="{request.url}" '
            f'headers={dict(request.headers)} '
            f'query_params={dict(request.query_params)}>')


class LoadBalancingPolicy:
    """Abstract class for load balancing policies."""

    def __init__(self) -> None:
        self.ready_replicas: List[str] = []

    def __init_subclass__(cls, name: str, default: bool = False):
        LB_POLICIES[name] = cls
        if default:
            global DEFAULT_LB_POLICY
            assert DEFAULT_LB_POLICY is None, (
                'Only one policy can be default.')
            DEFAULT_LB_POLICY = name

    @classmethod
    def make(cls, policy_name: Optional[str] = None) -> 'LoadBalancingPolicy':
        """Create a load balancing policy from a name."""
        if policy_name is None:
            policy_name = DEFAULT_LB_POLICY

        if policy_name not in LB_POLICIES:
            raise ValueError(f'Unknown load balancing policy: {policy_name}')
        return LB_POLICIES[policy_name]()

    def set_ready_replicas(self, ready_replicas: List[str]) -> None:
        raise NotImplementedError

    def select_replica(self, request: 'fastapi.Request') -> Optional[str]:
        replica = self._select_replica(request)
        if replica is not None:
            logger.info(f'Selected replica {replica} '
                        f'for request {_request_repr(request)}')
        else:
            logger.warning('No replica selected for request '
                           f'{_request_repr(request)}')
        return replica

    # TODO(tian): We should have an abstract class for Request to
    # compatible with all frameworks.
    def _select_replica(self, request: 'fastapi.Request') -> Optional[str]:
        raise NotImplementedError

    def probe_replicas(self) -> None:
        pass

    def pre_execute_hook(self, replica_url: str,
                         request: 'fastapi.Request') -> None:
        pass

    def post_execute_hook(self, replica_url: str,
                          request: 'fastapi.Request') -> None:
        pass


class RoundRobinPolicy(LoadBalancingPolicy, name='round_robin', default=True):
    """Round-robin load balancing policy."""

    def __init__(self) -> None:
        super().__init__()
        self.index = 0

    def set_ready_replicas(self, ready_replicas: List[str]) -> None:
        if set(self.ready_replicas) == set(ready_replicas):
            return
        # If the autoscaler keeps scaling up and down the replicas,
        # we need this shuffle to not let the first replica have the
        # most of the load.
        random.shuffle(ready_replicas)
        self.ready_replicas = ready_replicas
        self.index = 0

    def _select_replica(self, request: 'fastapi.Request') -> Optional[str]:
        del request  # Unused.
        if not self.ready_replicas:
            return None
        ready_replica_url = self.ready_replicas[self.index]
        self.index = (self.index + 1) % len(self.ready_replicas)
        return ready_replica_url


class LeastLoadPolicy(LoadBalancingPolicy, name='lpr'):
    """Least load load balancing policy."""

    def __init__(self) -> None:
        super().__init__()
        self.load_map: Dict[str, int] = collections.defaultdict(int)
        self.lock = threading.Lock()

    def set_ready_replicas(self, ready_replicas: List[str]) -> None:
        if set(self.ready_replicas) == set(ready_replicas):
            return
        with self.lock:
            self.ready_replicas = ready_replicas
            for r in self.ready_replicas:
                if r not in ready_replicas:
                    del self.load_map[r]
            for replica in ready_replicas:
                self.load_map[replica] = self.load_map.get(replica, 0)

    def _select_replica(self, request: 'fastapi.Request') -> Optional[str]:
        print('_select_replica', self.load_map)
        del request  # Unused.
        if not self.ready_replicas:
            return None
        with self.lock:
            return min(self.ready_replicas,
                       key=lambda replica: self.load_map.get(replica, 0))

    def pre_execute_hook(self, replica_url: str,
                         request: 'fastapi.Request') -> None:
        print('pre_execute_hook', self.load_map)
        del request  # Unused.
        with self.lock:
            self.load_map[replica_url] += 1

    def post_execute_hook(self, replica_url: str,
                          request: 'fastapi.Request') -> None:
        print('post_execute_hook', self.load_map)
        del request  # Unused.
        with self.lock:
            self.load_map[replica_url] -= 1


async def get_metric(session: aiohttp.ClientSession,
                     replica_url: str) -> Optional[Dict[str, Any]]:
    try:
        async with session.get(f'{replica_url}/metrics') as response:
            return await response.json()
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f'Failed to get metric from {replica_url}: {e}')
        return None


async def fetch_all_metrics(
        replica_urls: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
    async with aiohttp.ClientSession() as session:
        tasks = [
            get_metric(session, replica_url) for replica_url in replica_urls
        ]
        results = await asyncio.gather(*tasks)
        return dict(zip(replica_urls, results))


class LeastMemoryUsagePolicy(LoadBalancingPolicy, name='lmu'):
    """Least memory usage load balancing policy."""
    MEMORY_USAGE_METRIC_KEY = 'gauge_gpu_cache_usage'

    def __init__(self) -> None:
        super().__init__()
        self.memory_usage_map: Dict[str, float] = collections.defaultdict(float)
        self.lock = threading.Lock()

    def set_ready_replicas(self, ready_replicas: List[str]) -> None:
        if set(self.ready_replicas) == set(ready_replicas):
            return
        with self.lock:
            self.ready_replicas = ready_replicas
            for r in self.ready_replicas:
                if r not in ready_replicas:
                    del self.memory_usage_map[r]
            for replica in ready_replicas:
                self.memory_usage_map[replica] = self.memory_usage_map.get(
                    replica, 0)

    def probe_replicas(self) -> None:
        replica2metric = asyncio.run(fetch_all_metrics(self.ready_replicas))
        with self.lock:
            for replica, metric in replica2metric.items():
                if metric is not None:
                    if self.MEMORY_USAGE_METRIC_KEY not in metric:
                        logger.warning(
                            f'{self.MEMORY_USAGE_METRIC_KEY} not found in '
                            f'metric from {replica}: {metric}')
                    memory_usage: float = metric.get(
                        self.MEMORY_USAGE_METRIC_KEY, 0.5)
                else:
                    memory_usage = 0.5
                self.memory_usage_map[replica] = memory_usage
        logger.info(f'Updated memory usage map: {self.memory_usage_map}')

    def _select_replica(self, request: 'fastapi.Request') -> Optional[str]:
        del request  # Unused.
        if not self.ready_replicas:
            return None
        with self.lock:
            result = min(
                self.ready_replicas,
                key=lambda replica: self.memory_usage_map.get(replica, 0))
        logger.info(f'Selected replica {result} with memory usage '
                    f'{self.memory_usage_map[result]}')
        return result
