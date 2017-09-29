# -*- coding: utf-8 -*-
from __future__ import absolute_import


from .utils.visibility import getLogger
logger = getLogger(__name__)

from .exceptions import AnsibleContainerConfigException
from six import add_metaclass, iteritems, PY2, string_types, text_type

import container
import os.path

from .exceptions import AnsibleContainerConfigException, AnsibleContainerNotInitializedException
from .utils import get_metadata_from_role, get_defaults_from_role


'''
config_maps:
    mydata:
        data:
        data_from_file:

'''

class ConfigMap(object):

    def validate_config_maps(self, config_maps):
        for key in config_maps:
            if not isinstance(config_maps[key], dict):
                raise AnsibleContainerConfigException(
                    "Expecting config_maps to be a mapping."
                )
            if not config_maps.get('data') and not config_maps.get('data_from_file'):
                raise AnsibleContainerConfigException(
                    "Expecting ConfigMap {} to contain either a 'data' or 'data_from_file' key.".format(key)
                )
            if config_maps.get('data'):
                for map_key in config_maps[key]:
                    for data_key in config_maps[key][map_key]:
                        if data_key == 'data_from_file':
                            file_path = os.path.normpath(os.path.abspath(os.path.expanduser(
                                     config_maps[key][map_key][data_key])))
                            if not os.path.isfile(fs) and not os.path.isdir(file_path):
                                raise AnsibleContainerConfigException(
                                    "File or directory {} not found.".format(file_path)
                                )
                        if data_key == 'data':
                            if not isinstance(config_maps[key][map_key][data_key], dict):
                                raise AnsibleContainerConfigException(
                                    "Expecting data key {} in ConfigMap {} to be a mapping.".format(data_key, key)
                                )

    def get_data_for_key(self, config_maps, map_name, key_name):
        if not config_maps.get(map_name):
            raise AnsibleContainerConfigException(
                "ConfigMap {} not defined".format(map_name)
            )
        # if not config_maps[map_name].get(key_name):
        #     raise AnsibleContainerConfigException(
        #         "Key {} not found in ConfigMap {}".format(key_name, map_name)
        #
        data = dict()
        for key in config_maps[map_name]:
            if key == 'data':
                data.update(config_maps[map_name][key])
            if key == 'data_from_file':
                file_path = os.path.normpath(os.path.abspath(os.path.expanduser(config_maps[map_name][key])))
                file_basename = os.path.basename(fs)
                if os.path.isfile(fs):
                    with open(file_path, 'ro') as fs:
                        lines = fs.readlines()
                    data[file_basename] = '\n'.join(lines)
                if os.path.isdir(fs):

