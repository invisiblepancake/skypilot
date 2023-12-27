"""Autoscalers: perform autoscaling by monitoring metrics."""
import bisect
import dataclasses
import enum
import math
import time
import typing
from typing import Any, Callable, Dict, List, Optional, Union

from sky import sky_logging
from sky.serve import constants
from sky.serve import serve_state
from sky.serve import spot_policy

if typing.TYPE_CHECKING:
    from sky.serve import replica_managers
    from sky.serve import service_spec

logger = sky_logging.init_logger(__name__)


class AutoscalerDecisionOperator(enum.Enum):
    SCALE_UP = 'scale_up'
    SCALE_DOWN = 'scale_down'


@dataclasses.dataclass
class AutoscalerDecision:
    """Autoscaling decisions.

    |------------------------------------------------------------------------|
    | Operator   | TargetType                | Meaning                       |
    |------------|---------------------------|-------------------------------|
    | SCALE_UP   | Optional[Dict[str, Any]   | Resource override to add      |
    |------------|---------------------------|-------------------------------|
    | SCALE_DOWN | int                       | Replica id to remove          |
    |------------------------------------------------------------------------|
    """
    operator: AutoscalerDecisionOperator
    target: Union[Optional[Dict[str, Any]], int]

    # TODO(MaoZiming): Add a doc to elaborate on autoscaling policies.
    def __init__(self, operator: AutoscalerDecisionOperator,
                 target: Union[Optional[Dict[str, Any]], int]):

        assert (operator == AutoscalerDecisionOperator.SCALE_UP and
                (target is None or isinstance(target, dict))) or (
                    operator == AutoscalerDecisionOperator.SCALE_DOWN and
                    isinstance(target, int))
        self.operator = operator
        self.target = target

    def __repr__(self) -> str:
        return f'AutoscalerDecision({self.operator}, {self.target})'


class Autoscaler:
    """Abstract class for autoscalers."""

    def __init__(self, spec: 'service_spec.SkyServiceSpec') -> None:
        """Initialize the autoscaler.

        Variables:
            min_replicas: Minimum number of replicas.
            max_replicas: Maximum number of replicas. Default to fixed
                number of replicas, i.e. min_replicas == max_replicas.
            target_num_replicas: Target number of replicas output by autoscaler.
        """
        self.min_replicas: int = spec.min_replicas
        self.max_replicas: int = spec.max_replicas or spec.min_replicas
        self.target_num_replicas: int = spec.min_replicas

    def collect_request_information(
            self, request_aggregator_info: Dict[str, Any]) -> None:
        """Collect request information from aggregator for autoscaling."""
        raise NotImplementedError

    def evaluate_scaling(
        self,
        num_extra: int,
        replica_infos: List['replica_managers.ReplicaInfo'],
    ) -> List[AutoscalerDecision]:
        """Evaluate autoscale options based on replica information."""
        raise NotImplementedError


class RequestRateAutoscaler(Autoscaler):
    """RequestRateAutoscaler: Autoscale according to request rate.

    Scales when the number of requests in the given interval is above or below
    the threshold.
    """

    def __init__(self, spec: 'service_spec.SkyServiceSpec',
                 qps_window_size: int) -> None:
        """Initialize the request rate autoscaler.

        Variables:
            target_qps_per_replica: Target qps per replica for autoscaling.
            qps_window_size: Window size for qps calculating.
            request_timestamps: All request timestamps within the window.
            upscale_counter: counter for upscale number of replicas.
            downscale_counter: counter for downscale number of replicas.
            scale_up_consecutive_periods: period for scaling up.
            scale_down_consecutive_periods: period for scaling down.
        """
        super().__init__(spec)
        self.target_qps_per_replica: Optional[
            float] = spec.target_qps_per_replica
        self.qps_window_size: int = qps_window_size
        self.request_timestamps: List[float] = []
        self.overprovision = overprovision
        self.static_spot_provision = static_spot_provision
        self.auto_restart = spec.auto_restart
        self.upscale_counter: int = 0
        self.downscale_counter: int = 0
        self.scale_up_consecutive_periods: int = int(spec.upscale_delay_s /
                                                     self.frequency)
        self.scale_down_consecutive_periods: int = int(spec.downscale_delay_s /
                                                       self.frequency)
        self.target_num_replicas = spec.min_replicas
        self.default_slo_threshold = spec.default_slo_threshold
        self.scale_up_consecutive_periods: int = int(
            spec.upscale_delay_seconds /
            constants.AUTOSCALER_DEFAULT_DECISION_INTERVAL_SECONDS)
        self.scale_down_consecutive_periods: int = int(
            spec.downscale_delay_seconds /
            constants.AUTOSCALER_DEFAULT_DECISION_INTERVAL_SECONDS)
        # Target number of replicas is initialized to min replicas.
        # TODO(MaoZiming): add init replica numbers in SkyServe spec.
        self.target_num_replicas: int = spec.min_replicas
        self.bootstrap_done: bool = False

    def collect_request_information(
            self, request_aggregator_info: Dict[str, Any]) -> None:
        """Collect request information from aggregator for autoscaling.

        request_aggregator_info should be a dict with the following format:

        {
            'timestamps': [timestamp1 (float), timestamp2 (float), ...]
        }
        """
        self.request_timestamps.extend(
            request_aggregator_info.get('timestamps', []))
        current_time = time.time()
        index = bisect.bisect_left(self.request_timestamps,
                                   current_time - self.qps_window_size)
        self.request_timestamps = self.request_timestamps[index:]

    def evaluate_scaling(
        self,
        num_extra: int,
        replica_infos: List['replica_managers.ReplicaInfo'],
    ) -> List[AutoscalerDecision]:
        # Deprecated
        raise NotImplementedError

    def _get_desired_num_replicas(self) -> int:
        # Always return self.target_num_replicas when autoscaling
        # is not enabled, i.e. self.target_qps_per_replica is None.
        # In this case, self.target_num_replicas will be min_replicas.
        if self.target_qps_per_replica is None:
            return self.target_num_replicas

class OnDemandRateAutoscaler(RequestRateAutoscaler):
    """OnDemandRateAutoscaler: Use on-demand to autoscale based on request rate.

    This autoscaler uses on-demand instances to autoscale based on request
    rate.
    """

    def __init__(self,
                 spec: 'service_spec.SkyServiceSpec',
                 frequency: int,
                 rps_window_size: int,
                 overprovision: bool = False,
                 static_spot_provision: bool = False) -> None:
        super().__init__(spec, frequency, rps_window_size)

        self.target_qps_per_replica = spec.target_qps_per_replica
        assert self.target_qps_per_replica is not None
        self.target_num_replicas = spec.min_replicas

        self.upscale_counter: int = 0
        self.downscale_counter: int = 0

        self.scale_up_consecutive_periods: int = int(spec.upscale_delay_s /
                                                     self.frequency)
        self.scale_down_consecutive_periods: int = int(spec.downscale_delay_s /
                                                       self.frequency)
        self.overprovision = overprovision
        self.static_spot_provision = static_spot_provision
        self.auto_restart = spec.auto_restart

    def _get_on_demand_resources_override_dict(self) -> Dict[str, Any]:
        return {'use_spot': False, 'spot_recovery': None}

    def _get_desired_num_replicas(self) -> int:
        assert self.target_qps_per_replica is not None
        # Convert to requests per second.
        num_requests_per_second = len(
            self.request_timestamps) / self.qps_window_size
        target_num_replicas = math.ceil(num_requests_per_second /
                                        self.target_qps_per_replica)
        target_num_replicas = max(self.min_replicas,
                                  min(self.max_replicas, target_num_replicas))
        logger.info(f'Requests per second: {num_requests_per_second}, '
                    f'Current target number of replicas: {target_num_replicas}')

        if not self.bootstrap_done:
            self.bootstrap_done = True
            return target_num_replicas
        elif target_num_replicas > self.target_num_replicas:
            self.upscale_counter += 1
            self.downscale_counter = 0
            if self.upscale_counter >= self.scale_up_consecutive_periods:
                self.upscale_counter = 0
                return target_num_replicas
        elif target_num_replicas < self.target_num_replicas:
            self.downscale_counter += 1
            self.upscale_counter = 0
            if self.downscale_counter >= self.scale_down_consecutive_periods:
                self.downscale_counter = 0
                return target_num_replicas
        else:
            self.upscale_counter = self.downscale_counter = 0
        return self.target_num_replicas

    def evaluate_scaling(
        self,
        num_extra: int,
        replica_infos: List['replica_managers.ReplicaInfo'],
    ) -> List[AutoscalerDecision]:
        # TODO(tian): Consider non-alive replicas.
        assert self.auto_restart
        alive_replica_infos = [info for info in replica_infos if info.is_alive]

        # Don't count over-provision here.
        self.target_num_replicas = self._get_desired_num_replicas()
        logger.info(
            f'Final target number of replicas: {self.target_num_replicas} '
            f'({self.target_num_replicas} with '
            f'over-provision), Upscale counter: {self.upscale_counter}/'
            f'{self.scale_up_consecutive_periods}, '
            f'Downscale counter: {self.downscale_counter}/'
            f'{self.scale_down_consecutive_periods}')

        num_alive_on_demand = 0
        for info in alive_replica_infos:
            if info.is_spot:
                assert False, ('OnDemandRateAutoscaler',
                               'should not have spot instances.')
            else:
                num_alive_on_demand += 1

        logger.info(
            f'Number of alive on-demand instances: {num_alive_on_demand}')

        scaling_options = []
        all_replica_ids_to_scale_down: List[int] = []

        def _get_replica_ids_to_scale_down(
            info_filter: Callable[['replica_managers.ReplicaInfo'], bool],
            status_order: List['serve_state.ReplicaStatus'],
            num_limit: int,
        ) -> List[int]:
            replica_ids_to_scale_down: List[int] = []
            for target_status in status_order:
                for info in alive_replica_infos:
                    if info_filter(info) and info.status == target_status:
                        if len(replica_ids_to_scale_down) >= num_limit:
                            return replica_ids_to_scale_down
                        replica_ids_to_scale_down.append(info.replica_id)
            for info in alive_replica_infos:
                if info_filter(info) and info.status not in status_order:
                    if len(replica_ids_to_scale_down) >= num_limit:
                        return replica_ids_to_scale_down
                    replica_ids_to_scale_down.append(info.replica_id)
            return replica_ids_to_scale_down

        num_to_provision = self.target_num_replicas
        if self.overprovision:
            num_to_provision += num_extra

        if num_alive_on_demand < num_to_provision:
            num_demand_to_scale_up = num_to_provision - num_alive_on_demand

            for _ in range(num_demand_to_scale_up):
                scaling_options.append(
                    AutoscalerDecision(
                        AutoscalerDecisionOperator.SCALE_UP,
                        target=self._get_on_demand_resources_override_dict()))

        elif num_alive_on_demand > num_to_provision:

            num_demand_to_scale_down = num_alive_on_demand - num_to_provision
            all_replica_ids_to_scale_down.extend(
                _get_replica_ids_to_scale_down(
                    info_filter=lambda info: not info.is_spot,
                    status_order=serve_state.ReplicaStatus.
                    scale_down_decision_order(),
                    num_limit=num_demand_to_scale_down,
                ))

        for replica_id in all_replica_ids_to_scale_down:
            scaling_options.append(
                AutoscalerDecision(AutoscalerDecisionOperator.SCALE_DOWN,
                                   target=replica_id))

        if not scaling_options:
            logger.info('No scaling needed.')
        return scaling_options


class SpotRequestRateAutoscaler(RequestRateAutoscaler):
    """SpotRequestRateAutoscaler: Use spot to autoscale based on request rate.

    This autoscaler uses spot instances to save cost while maintaining the
    same performance as OnDemand instances.
    """

    def __init__(self,
                 spec: 'service_spec.SkyServiceSpec',
                 frequency: int,
                 rps_window_size: int,
                 overprovision: bool = False,
                 static_spot_provision: bool = False,
                 use_safety_net: bool = False) -> None:
        super().__init__(spec, frequency, rps_window_size)
        assert (spec.spot_placer is not None and spec.spot_zones is not None and
                spec.num_extra is not None and
                spec.target_qps_per_replica is not None)
        self.spot_placer = spot_policy.SpotPlacer.from_spec(spec)
        self.target_qps_per_replica: float = spec.target_qps_per_replica
        self.target_num_replicas = spec.min_replicas
        self.num_init_replicas = spec.num_init_replicas
        self.has_init = False
        self.upscale_counter: int = 0
        self.downscale_counter: int = 0

        self.scale_up_consecutive_periods: int = int(spec.upscale_delay_s /
                                                     self.frequency)
        self.scale_down_consecutive_periods: int = int(spec.downscale_delay_s /
                                                       self.frequency)
        self.static_spot_provision = static_spot_provision
        self.overprovision = overprovision
        self.use_safety_net = use_safety_net
        self.meet_safety_net_count = 0
        self.miss_safety_net_count = 0
        self.auto_restart = spec.auto_restart

    def _get_spot_resources_override_dict(self) -> Dict[str, Any]:
        return {'use_spot': True, 'spot_recovery': None}

    def _get_on_demand_resources_override_dict(self) -> Dict[str, Any]:
        return {'use_spot': False, 'spot_recovery': None}

    def _get_desired_num_replicas(self) -> int:
        # Convert to requests per second.
        num_requests_per_second = len(
            self.request_timestamps) / self.rps_window_size
        target_num_replicas = math.ceil(num_requests_per_second /
                                        self.target_qps_per_replica)
        target_num_replicas = max(self.min_replicas,
                                  min(self.max_replicas, target_num_replicas))
        logger.info(f'Requests per second: {num_requests_per_second}, '
                    f'Current target number of replicas: {target_num_replicas}')

        if target_num_replicas > self.target_num_replicas:
            self.upscale_counter += 1
            self.downscale_counter = 0
            if self.upscale_counter >= self.scale_up_consecutive_periods:
                self.upscale_counter = 0
                return target_num_replicas
        elif target_num_replicas < self.target_num_replicas:
            self.downscale_counter += 1
            self.upscale_counter = 0
            if self.downscale_counter >= self.scale_down_consecutive_periods:
                self.downscale_counter = 0
                return target_num_replicas
        else:
            self.upscale_counter = self.downscale_counter = 0
        return self.target_num_replicas

    def handle_active_history(self, history: List[str]) -> None:
        for zone in history:
            self.spot_placer.handle_active(zone)

    def handle_preemption_history(self, history: List[str]) -> None:
        for zone in history:
            self.spot_placer.handle_preemption(zone)

    def evaluate_scaling(
        self,
        num_extra: int,
        replica_infos: List['replica_managers.ReplicaInfo'],
    ) -> List[AutoscalerDecision]:
        # TODO(tian): Consider non-alive replicas.

        assert self.auto_restart
        alive_replica_infos = [info for info in replica_infos if info.is_alive]
        # Don't count over-provision here.
        if not self.has_init and self.num_init_replicas is not None:
            self.target_num_replicas = self.num_init_replicas
            self.has_init = True
        else:
            self.target_num_replicas = self._get_desired_num_replicas()
        logger.info(
            f'Final target number of replicas: {self.target_num_replicas} '
            f'({self.target_num_replicas + num_extra} with '
            f'over-provision), Upscale counter: {self.upscale_counter}/'
            f'{self.scale_up_consecutive_periods}, '
            f'Downscale counter: {self.downscale_counter}/'
            f'{self.scale_down_consecutive_periods}')

        num_alive_spot, num_ready_spot = 0, 0
        num_alive_on_demand, num_ready_on_demand = 0, 0
        for info in alive_replica_infos:
            if info.is_spot:
                if info.status == serve_state.ReplicaStatus.READY:
                    num_ready_spot += 1
                num_alive_spot += 1
            else:
                if info.status == serve_state.ReplicaStatus.READY:
                    num_ready_on_demand += 1
                num_alive_on_demand += 1
        logger.info(
            f'Number of alive spot instances: {num_alive_spot}, '
            f'Number of ready spot instances: {num_ready_spot}, '
            f'Number of alive on-demand instances: {num_alive_on_demand}, '
            f'Number of ready on-demand instances: {num_ready_on_demand}')

        if isinstance(self.spot_placer, spot_policy.HistoricalSpotPlacer):
            log_zone_to_type = {
                zone: zone_type.value
                for zone, zone_type in self.spot_placer.zone2type.items()
            }
            logger.info(f'Current zone to type: {log_zone_to_type}')

        scaling_options = []
        all_replica_ids_to_scale_down: List[int] = []

        def _get_replica_ids_to_scale_down(
            info_filter: Callable[['replica_managers.ReplicaInfo'], bool],
            status_order: List['serve_state.ReplicaStatus'],
            num_limit: int,
        ) -> List[int]:
            replica_ids_to_scale_down: List[int] = []
            for target_status in status_order:
                for info in alive_replica_infos:
                    if info_filter(info) and info.status == target_status:
                        if len(replica_ids_to_scale_down) >= num_limit:
                            return replica_ids_to_scale_down
                        replica_ids_to_scale_down.append(info.replica_id)
            for info in alive_replica_infos:
                if info_filter(info) and info.status not in status_order:
                    if len(replica_ids_to_scale_down) >= num_limit:
                        return replica_ids_to_scale_down
                    replica_ids_to_scale_down.append(info.replica_id)
            return replica_ids_to_scale_down

        num_to_provision = (self.target_num_replicas + num_extra)

        # Scale spot instances.
        current_considered_zones: List[str] = []
        if num_alive_spot < num_to_provision:
            # Not enough spot instances, scale up.
            num_spot_to_scale_up = num_to_provision - num_alive_spot
            for _ in range(num_spot_to_scale_up):
                spot_override = self._get_spot_resources_override_dict()
                zone = self.spot_placer.select(alive_replica_infos,
                                               current_considered_zones)
                current_considered_zones.append(zone)
                spot_override.update({'zone': zone})
                logger.info(f'Chosen zone {zone} with {self.spot_placer}')
                scaling_options.append(
                    AutoscalerDecision(AutoscalerDecisionOperator.SCALE_UP,
                                       target=spot_override))
        elif num_alive_spot > num_to_provision:
            # Too many spot instances, scale down.
            num_spot_to_scale_down = num_alive_spot - num_to_provision
            all_replica_ids_to_scale_down.extend(
                _get_replica_ids_to_scale_down(
                    info_filter=lambda info: info.is_spot,
                    status_order=serve_state.ReplicaStatus.
                    scale_down_decision_order(),
                    num_limit=num_spot_to_scale_down,
                ))

        # OnDemand fallback.
        if not self.static_spot_provision:

            if self.use_safety_net:
                if num_ready_spot + num_ready_on_demand >= num_to_provision:
                    self.meet_safety_net_count += 1
                else:
                    self.miss_safety_net_count += 1

            num_demand_to_scale_up, num_demand_to_scale_down = 0, 0
            if (self.use_safety_net and self.meet_safety_net_count /
                (self.meet_safety_net_count + self.miss_safety_net_count) <
                    self.default_slo_threshold and
                    self.meet_safety_net_count + self.miss_safety_net_count >
                    constants.DEFAULT_SLO_COUNT_START):
                # Enable OnDemand fallback.
                num_demand_to_scale_up = (self.target_num_replicas -
                                          num_alive_on_demand)

            elif num_ready_spot + num_alive_on_demand < num_to_provision:
                # Enable OnDemand fallback.
                num_demand_to_scale_up = min(
                    self.target_num_replicas,
                    num_to_provision - num_ready_spot) - num_alive_on_demand

            elif num_ready_spot + num_alive_on_demand > num_to_provision:
                # OnDemand fallback is not needed.
                num_demand_to_scale_down = (num_ready_spot +
                                            num_alive_on_demand -
                                            num_to_provision)

            if num_demand_to_scale_up > 0:
                for _ in range(num_demand_to_scale_up):
                    scaling_options.append(
                        AutoscalerDecision(
                            AutoscalerDecisionOperator.SCALE_UP,
                            target=self._get_on_demand_resources_override_dict(
                            )))
            elif num_demand_to_scale_down > 0:
                all_replica_ids_to_scale_down.extend(
                    _get_replica_ids_to_scale_down(
                        info_filter=lambda info: not info.is_spot,
                        status_order=serve_state.ReplicaStatus.
                        scale_down_decision_order(),
                        num_limit=num_demand_to_scale_down,
                    ))

        for replica_id in all_replica_ids_to_scale_down:
            scaling_options.append(
                AutoscalerDecision(AutoscalerDecisionOperator.SCALE_DOWN,
                                   target=replica_id))
        if not scaling_options:
            logger.info('No scaling needed.')
        return scaling_options
