"""This module contains schemas used to validate objects.

Schemas conform to the JSON Schema specification as defined at
https://json-schema.org/
"""


def _resources_properties_without_accelerators():
    # To avoid circular imports, only import when needed.
    # pylint: disable=import-outside-toplevel
    from sky.clouds import service_catalog
    return {
        'cloud': {
            'type': 'string',
            'case_insensitive_enum': list(service_catalog.ALL_CLOUDS)
        },
        'region': {
            'type': 'string',
        },
        'zone': {
            'type': 'string',
        },
        'cpus': {
            'anyOf': [{
                'type': 'string',
            }, {
                'type': 'number',
            }],
        },
        'memory': {
            'anyOf': [{
                'type': 'string',
            }, {
                'type': 'number',
            }],
        },
        'instance_type': {
            'type': 'string',
        },
        'use_spot': {
            'type': 'boolean',
        },
        'job_recovery': {
            'type': 'string',
        },
        'spot_recovery': {
            'type': 'string',
            # Failed to import recovery_strategy.RECOVERY_STRATEGIES due to
            # circular import.
        },
        'disk_size': {
            'type': 'integer',
        },
        'disk_tier': {
            'type': 'string',
        },
        'ports': {
            'anyOf': [{
                'type': 'string',
            }, {
                'type': 'integer',
            }, {
                'type': 'array',
                'items': {
                    'anyOf': [{
                        'type': 'string',
                    }, {
                        'type': 'integer',
                    }]
                }
            }],
        },
        'accelerator_args': {
            'type': 'object',
            'required': [],
            'additionalProperties': False,
            'properties': {
                'runtime_version': {
                    'type': 'string',
                },
                'tpu_name': {
                    'type': 'string',
                },
                'tpu_vm': {
                    'type': 'boolean',
                }
            }
        },
        'image_id': {
            'anyOf': [{
                'type': 'string',
            }, {
                'type': 'object',
                'required': [],
            }]
        }
    }


def _only_one_of_two_field_config(field1: str, field2: str):
    return {
        'oneOf': [{
            'required': [field1],
            'not': {
                'required': [field2]
            }
        }, {
            'required': [field2],
            'not': {
                'required': [field1]
            }
        }, {
            'not': {
                'anyOf': [{
                    'required': [field1]
                }, {
                    'required': [field2]
                }]
            }
        }]
    }


def get_single_resources_schema():

    return {
        '$schema': 'https://json-schema.org/draft/2020-12/schema',
        'type': 'object',
        'required': [],
        'additionalProperties': False,
        'properties': {
            'accelerators': {
                'anyOf': [{
                    'type': 'string',
                }, {
                    'type': 'object',
                    'required': [],
                    'maxProperties': 1,
                    'additionalProperties': {
                        'type': 'number'
                    }
                }]
            },
            **_resources_properties_without_accelerators()
        }
    }


def get_resources_schema():
    # To avoid circular imports, only import when needed.
    # pylint: disable=import-outside-toplevel
    return {
        '$schema': 'http://json-schema.org/draft-07/schema#',
        'type': 'object',
        'required': [],
        'additionalProperties': False,
        'properties': {
            'accelerators': {
                # {'V100:1', 'A100:1'} will be
                # read as a string and converted to dict.
                'anyOf': [{
                    'type': 'string',
                }, {
                    'type': 'object',
                    'required': [],
                    'additionalProperties': {
                        'anyOf': [{
                            'type': 'null',
                        }, {
                            'type': 'number',
                        }]
                    }
                }, {
                    'type': 'array',
                    'items': {
                        'type': 'string',
                    }
                }]
            },
            **_resources_properties_without_accelerators(),
            'any_of': {
                'type': 'array',
                'items': {
                    k: v
                    for k, v in get_single_resources_schema().items()
                    # Validation may fail if $schema is included.
                    if k != '$schema'
                },
            },
            'ordered': {
                'type': 'array',
                'items': {
                    k: v
                    for k, v in get_single_resources_schema().items()
                    # Validation may fail if $schema is included.
                    if k != '$schema'
                },
            }
        },
        # Avoid job_recovery and spot_recovery being present at the same time.
        **_only_one_of_two_field_config('job_recovery', 'spot_recovery')
    }


def get_storage_schema():
    # pylint: disable=import-outside-toplevel
    from sky.data import storage
    return {
        '$schema': 'https://json-schema.org/draft/2020-12/schema',
        'type': 'object',
        'required': [],
        'additionalProperties': False,
        'properties': {
            'name': {
                'type': 'string',
            },
            'source': {
                'anyOf': [{
                    'type': 'string',
                }, {
                    'type': 'array',
                    'minItems': 1,
                    'items': {
                        'type': 'string'
                    }
                }]
            },
            'store': {
                'type': 'string',
                'case_insensitive_enum': [
                    type.value for type in storage.StoreType
                ]
            },
            'persistent': {
                'type': 'boolean',
            },
            'mode': {
                'type': 'string',
                'case_insensitive_enum': [
                    mode.value for mode in storage.StorageMode
                ]
            },
            '_force_delete': {
                'type': 'boolean',
            }
        }
    }


def get_service_schema():
    """Schema for top-level `service:` field (for SkyServe)."""
    return {
        '$schema': 'https://json-schema.org/draft/2020-12/schema',
        'type': 'object',
        'required': ['readiness_probe'],
        'additionalProperties': False,
        'properties': {
            'readiness_probe': {
                'anyOf': [{
                    'type': 'string',
                }, {
                    'type': 'object',
                    'required': ['path'],
                    'additionalProperties': False,
                    'properties': {
                        'path': {
                            'type': 'string',
                        },
                        'initial_delay_seconds': {
                            'type': 'number',
                        },
                        'post_data': {
                            'anyOf': [{
                                'type': 'string',
                            }, {
                                'type': 'object',
                            }]
                        }
                    }
                }]
            },
            'replica_policy': {
                'type': 'object',
                'required': ['min_replicas'],
                'additionalProperties': False,
                'properties': {
                    'min_replicas': {
                        'type': 'integer',
                        'minimum': 0,
                    },
                    'max_replicas': {
                        'type': 'integer',
                        'minimum': 0,
                    },
                    'target_qps_per_replica': {
                        'type': 'number',
                        'minimum': 0,
                    },
                    'dynamic_ondemand_fallback': {
                        'type': 'boolean',
                    },
                    'base_ondemand_fallback_replicas': {
                        'type': 'integer',
                        'minimum': 0,
                    },
                    'upscale_delay_seconds': {
                        'type': 'number',
                    },
                    'downscale_delay_seconds': {
                        'type': 'number',
                    },
                    # TODO(MaoZiming): Fields `qps_upper_threshold`,
                    # `qps_lower_threshold` and `auto_restart` are deprecated.
                    # Temporarily keep these fields for backward compatibility.
                    # Remove after 2 minor release, i.e., 0.6.0.
                    'auto_restart': {
                        'type': 'boolean',
                    },
                    'qps_upper_threshold': {
                        'type': 'number',
                    },
                    'qps_lower_threshold': {
                        'type': 'number',
                    },
                }
            },
            'replicas': {
                'type': 'integer',
            },
        }
    }


def get_task_schema():
    return {
        '$schema': 'https://json-schema.org/draft/2020-12/schema',
        'type': 'object',
        'required': [],
        'additionalProperties': False,
        'properties': {
            'name': {
                'type': 'string',
            },
            'workdir': {
                'type': 'string',
            },
            'event_callback': {
                'type': 'string',
            },
            'num_nodes': {
                'type': 'integer',
            },
            # resources config is validated separately using RESOURCES_SCHEMA
            'resources': {
                'type': 'object',
            },
            # storage config is validated separately using STORAGE_SCHEMA
            'file_mounts': {
                'type': 'object',
            },
            # service config is validated separately using SERVICE_SCHEMA
            'service': {
                'type': 'object',
            },
            'setup': {
                'type': 'string',
            },
            'run': {
                'type': 'string',
            },
            'envs': {
                'type': 'object',
                'required': [],
                'patternProperties': {
                    # Checks env keys are valid env var names.
                    '^[a-zA-Z_][a-zA-Z0-9_]*$': {
                        'type': 'string'
                    }
                },
                'additionalProperties': False,
            },
            # inputs and outputs are experimental
            'inputs': {
                'type': 'object',
                'required': [],
                'maxProperties': 1,
                'additionalProperties': {
                    'type': 'number'
                }
            },
            'outputs': {
                'type': 'object',
                'required': [],
                'maxProperties': 1,
                'additionalProperties': {
                    'type': 'number'
                }
            },
        }
    }


def get_cluster_schema():
    return {
        '$schema': 'https://json-schema.org/draft/2020-12/schema',
        'type': 'object',
        'required': ['cluster', 'auth'],
        'additionalProperties': False,
        'properties': {
            'cluster': {
                'type': 'object',
                'required': ['ips', 'name'],
                'additionalProperties': False,
                'properties': {
                    'ips': {
                        'type': 'array',
                        'items': {
                            'type': 'string',
                        }
                    },
                    'name': {
                        'type': 'string',
                    },
                }
            },
            'auth': {
                'type': 'object',
                'required': ['ssh_user', 'ssh_private_key'],
                'additionalProperties': False,
                'properties': {
                    'ssh_user': {
                        'type': 'string',
                    },
                    'ssh_private_key': {
                        'type': 'string',
                    },
                }
            },
            'python': {
                'type': 'string',
            },
        }
    }


_NETWORK_CONFIG_SCHEMA = {
    'vpc_name': {
        'oneOf': [{
            'type': 'string',
        }, {
            'type': 'null',
        }],
    },
    'use_internal_ips': {
        'type': 'boolean',
    },
    'ssh_proxy_command': {
        'oneOf': [{
            'type': 'string',
        }, {
            'type': 'null',
        }, {
            'type': 'object',
            'required': [],
            'additionalProperties': {
                'anyOf': [
                    {
                        'type': 'string'
                    },
                    {
                        'type': 'null'
                    },
                ]
            }
        }]
    },
}

_INSTANCE_TAGS_SCHEMA = {
    'instance_tags': {
        'type': 'object',
        'required': [],
        'additionalProperties': {
            'type': 'string',
        },
    },
}

_REMOTE_IDENTITY_SCHEMA = {
    'remote_identity': {
        'type': 'string',
        'case_insensitive_enum': ['LOCAL_CREDENTIALS', 'SERVICE_ACCOUNT'],
    }
}

REMOTE_IDENTITY_DEFAULT = 'LOCAL_CREDENTIALS'


def get_config_schema():
    # pylint: disable=import-outside-toplevel
    from sky.utils import kubernetes_enums

    resources_schema = {
        k: v
        for k, v in get_resources_schema().items()
        # Validation may fail if $schema is included.
        if k != '$schema'
    }
    resources_schema['properties'].pop('ports')
    controller_resources_schema = {
        'type': 'object',
        'required': [],
        'additionalProperties': False,
        'properties': {
            'controller': {
                'type': 'object',
                'required': [],
                'additionalProperties': False,
                'properties': {
                    'resources': resources_schema,
                }
            },
        }
    }
    cloud_configs = {
        'aws': {
            'type': 'object',
            'required': [],
            'additionalProperties': False,
            'properties': {
                'security_group_name': {
                    'type': 'string',
                },
                **_INSTANCE_TAGS_SCHEMA,
                **_NETWORK_CONFIG_SCHEMA,
            }
        },
        'gcp': {
            'type': 'object',
            'required': [],
            'additionalProperties': False,
            'properties': {
                'prioritize_reservations': {
                    'type': 'boolean',
                },
                'specific_reservations': {
                    'type': 'array',
                    'items': {
                        'type': 'string',
                    },
                },
                **_INSTANCE_TAGS_SCHEMA,
                **_NETWORK_CONFIG_SCHEMA,
            }
        },
        'kubernetes': {
            'type': 'object',
            'required': [],
            'additionalProperties': False,
            'properties': {
                'networking': {
                    'type': 'string',
                    'case_insensitive_enum': [
                        type.value
                        for type in kubernetes_enums.KubernetesNetworkingMode
                    ]
                },
                'ports': {
                    'type': 'string',
                    'case_insensitive_enum': [
                        type.value
                        for type in kubernetes_enums.KubernetesPortMode
                    ]
                },
                'pod_config': {
                    'type': 'object',
                    'required': [],
                    # Allow arbitrary keys since validating pod spec is hard
                    'additionalProperties': True,
                },
                'custom_metadata': {
                    'type': 'object',
                    'required': [],
                    # Allow arbitrary keys since validating metadata is hard
                    'additionalProperties': True,
                    # Disallow 'name' and 'namespace' keys in this dict
                    'not': {
                        'anyOf': [{
                            'required': ['name']
                        }, {
                            'required': ['namespace']
                        }]
                    }
                },
                'remote_identity': {
                    'type': 'string'
                },
                'provision_timeout': {
                    'type': 'integer',
                },
            }
        },
        'oci': {
            'type': 'object',
            'required': [],
            'properties': {},
            # Properties are either 'default' or a region name.
            'additionalProperties': {
                'type': 'object',
                'required': [],
                'additionalProperties': False,
                'properties': {
                    'compartment_ocid': {
                        'type': 'string',
                    },
                    'image_tag_general': {
                        'type': 'string',
                    },
                    'image_tag_gpu': {
                        'type': 'string',
                    },
                    'vcn_subnet': {
                        'type': 'string',
                    },
                }
            },
        },
    }

    for config in cloud_configs.values():
        for key in _REMOTE_IDENTITY_SCHEMA:
            if key not in config['properties']:  # Add if not already present
                config['properties'].update(_REMOTE_IDENTITY_SCHEMA)
                break
    return {
        '$schema': 'https://json-schema.org/draft/2020-12/schema',
        'type': 'object',
        'required': [],
        'additionalProperties': False,
        'properties': {
            'managed_job': controller_resources_schema,
            'spot': controller_resources_schema,
            'serve': controller_resources_schema,
            **cloud_configs,
        },
        # Avoid spot and managed_job being present at the same time.
        **_only_one_of_two_field_config('spot', 'managed_job')
    }
