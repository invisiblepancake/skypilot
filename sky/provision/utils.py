"""Common utility functions for the sky provisioning system."""

import math
import re
from typing import Optional, Tuple, Union

from sky.utils import common_utils


class VirtualInstanceType:
    """Class to represent the "Instance Type" in a cloud without such notion.

    Since some clouds do not have a notion of instances, we generate virtual
    instance types that represent the resources requested by a node.

    This name captures the following resource requests:
        - CPU
        - Memory
        - Accelerators

    The name format is "{n}CPU--{k}GB" where n is the number of vCPUs and
    k is the amount of memory in GB. Accelerators can be specified by
    appending "--{a}{type}" where a is the number of accelerators and
    type is the accelerator type.

    CPU and memory can be specified as floats. Accelerator count must be int.

    Examples:
        - 4CPU--16GB
        - 0.5CPU--1.5GB
        - 4CPU--16GB--1V100
    """

    def __init__(self,
                 cpus: float,
                 memory: float,
                 accelerator_count: Optional[int] = None,
                 accelerator_type: Optional[str] = None):
        self.cpus = cpus
        self.memory = memory
        self.accelerator_count = accelerator_count
        self.accelerator_type = accelerator_type

    @property
    def name(self) -> str:
        """Returns the name of the instance."""
        assert self.cpus is not None
        assert self.memory is not None
        name = (f'{common_utils.format_float(self.cpus)}CPU--'
                f'{common_utils.format_float(self.memory)}GB')
        if self.accelerator_count:
            name += f'--{self.accelerator_count}{self.accelerator_type}'
        return name

    @staticmethod
    def is_valid_instance_type(name: str) -> bool:
        """Returns whether the given name is a valid instance type."""
        pattern = re.compile(r'^(\d+(\.\d+)?CPU--\d+(\.\d+)?GB)(--\d+\S+)?$')
        return bool(pattern.match(name))

    @classmethod
    def _parse_instance_type(
            cls,
            name: str) -> Tuple[float, float, Optional[int], Optional[str]]:
        """Parses and returns resources from the given InstanceType name

        Returns:
            cpus | float: Number of CPUs
            memory | float: Amount of memory in GB
            accelerator_count | float: Number of accelerators
            accelerator_type | str: Type of accelerator
        """
        pattern = re.compile(
            r'^(?P<cpus>\d+(\.\d+)?)CPU--(?P<memory>\d+(\.\d+)?)GB(?:--(?P<accelerator_count>\d+)(?P<accelerator_type>\S+))?$'  # pylint: disable=line-too-long
        )
        match = pattern.match(name)
        if match:
            cpus = float(match.group('cpus'))
            memory = float(match.group('memory'))
            accelerator_count = match.group('accelerator_count')
            accelerator_type = match.group('accelerator_type')
            if accelerator_count:
                accelerator_count = int(accelerator_count)
                accelerator_type = str(accelerator_type)
            else:
                accelerator_count = None
                accelerator_type = None
            return cpus, memory, accelerator_count, accelerator_type
        else:
            raise ValueError(f'Invalid instance name: {name}')

    @classmethod
    def from_instance_type(cls, name: str) -> 'VirtualInstanceType':
        """Returns an instance name object from the given name."""
        if not cls.is_valid_instance_type(name):
            raise ValueError(f'Invalid instance name: {name}')
        cpus, memory, accelerator_count, accelerator_type = \
            cls._parse_instance_type(name)
        return cls(cpus=cpus,
                   memory=memory,
                   accelerator_count=accelerator_count,
                   accelerator_type=accelerator_type)

    @classmethod
    def from_resources(cls,
                       cpus: float,
                       memory: float,
                       accelerator_count: Union[float, int] = 0,
                       accelerator_type: str = '') -> 'VirtualInstanceType':
        """Returns an instance name object from the given resources.

        If accelerator_count is not an int, it will be rounded up since GPU
        requests in Kubernetes must be int.
        """
        name = f'{cpus}CPU--{memory}GB'
        # Round up accelerator_count if it is not an int.
        accelerator_count = math.ceil(accelerator_count)
        if accelerator_count > 0:
            name += f'--{accelerator_count}{accelerator_type}'
        return cls(cpus=cpus,
                   memory=memory,
                   accelerator_count=accelerator_count,
                   accelerator_type=accelerator_type)

    def __str__(self):
        return self.name
