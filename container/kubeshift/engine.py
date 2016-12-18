# -*- coding: utf-8 -*-
from __future__ import absolute_import

import logging
import json

from ..engine import BaseEngine
from ..utils import load_shipit_engine
from ..exceptions import AnsibleContainerKubeShiftException

try:
    from kubeshift import Config, OpenshiftClient, KubernetesClient
    from kubeshift.validator import validate
    from kubeshift.exceptions import KubeRequestError, KubeShiftError
    from kubeshift.constants import DEFAULT_NAMESPACE
except Exception as exc:
    raise AnsibleContainerKubeShiftException("{}. Try `pip install -e git+https://github.com/cdrage/"
                                             "kubeshift.git@master#egg=kubeshift`".format(exc.message))


logger = logging.getLogger(__name__)


class Engine(BaseEngine):

    engine_name = 'kubeshift'
    orchestrator_name = ''
    builder_container_img_name = 'ansible-container'
    builder_container_img_tag = 'ansible-container-builder'
    default_registry_url = 'https://index.docker.io/v1/'
    default_registry_name = 'dockerhub'
    _client = None
    _orchestrated_hosts = None
    _shipit_cls = None
    namespace = None
    api_version = ''
    temp_dir = None

    def __init__(self, base_path, project_name, params={}):
        super(Engine, self).__init__(base_path, project_name, params)
        kube_config = Config.from_file(filepath=None)
        if params.get('context_name'):
            kube_config.set_current_context(self.params.get('context_name'))
        self.namespace = params.get('namespace', DEFAULT_NAMESPACE)
        if params.get('cluster_type') not in ('openshift', 'kube'):
            raise AnsibleContainerKubeShiftException(u"Invalid cluster type. Expected one of: 'openshift', 'kube'")
        if params.get('cluster_type') == 'openshift':
            self._client = OpenshiftClient(kube_config)
            self._shipit_cls = 'openshift'
        elif params.get('cluster_type') in ('kube', 'kubernetes'):
            self._client = KubernetesClient(kube_config)
            self._shipit_cls = 'kube'
        logger.debug("API resources:")
        logger.debug(json.dumps(self._client.api_resources, indent=4))


    def all_hosts_in_orchestration(self):
        """
        List all hosts being orchestrated by the compose engine.

        :return: list of strings
        """
        services = self.config.get('services')
        return list(services.keys()) if services else []

    def orchestrate(self, operation, temp_dir, hosts=[], context={}):
        '''
        Launch or stop the project on the cluster

        :param operation:
        :param temp_dir:
        :param hosts:
        :param context:
        :return:
        '''
        shipit_config = load_shipit_engine(self._shipit_cls, project_name=self.project_name, base_path=self.base_path,
                                           config=self.config).get_config()
        if not self._shipit_config_is_valid(shipit_config):
            raise AnsibleContainerKubeShiftException("Found error in configuration. Deployment terminated.")

        if operation == 'run':
            for service_type, configs in shipit_config.items():
                getattr(self, '_create_or_update_{}'.format(service_type))(configs)
        if operation == 'stop':
            pass

    def _shipit_config_is_valid(self, shipit_config):
        valid = True
        for config_type, configs in shipit_config.items():
            valid = True
            for config in configs:
                try:
                    validate(config)
                except KubeShiftError as exc:
                    valid = False
                    logger.error("Error in {} config".format(config_type))
                    logger.error(json.dumps(config, indent=4))
                    logger.error(exc.message)
        return valid

    def _create_or_update_services(self, services):
        for service in services:
            name = service['metadata']['name']
            logger.debug("Testing service {}".format(name))
            try:
                existing_service = self._client.services(namespace=self.namespace).by_name(name)
            except KubeRequestError:
                logger.debug("Creating service {}".format(name))
                logger.debug(json.dumps(service, indent=4))
                self._client.create(service, namespace=self.namespace)
                continue
            logger.debug("Found existing service:")
            logger.debug(json.dumps(existing_service, indent=4))

            labels = dict_in_dict(service['metadata'].get('labels'),
                                  existing_service['metadata'].get('labels', {}))
            if not labels:
                logger.debug("Labels are different")
                logger.debug(json.dumps(service['metadata'].get('labels'), indent=4))
            else:
                selectors = dict_in_dict(service.get('spec', {}).get('selector'),
                                         existing_service['spec'].get('selector', {}))
                if not selectors:
                    logger.debug("Selectors are different")
                    logger.debug(json.dumps(service.get('spec', {}).get('selector'), indent=4))
                else:
                    ports = list_of_dicts_in_list_of_dicts(
                        service.get('spec', {}).get('ports'),
                        existing_service['spec'].get('ports', [])
                    )
                    if not ports:
                        logger.debug("Ports are different")
                        logger.debug(json.dumps(service.get('spec', {}).get('ports'), indent=4))
                    else:
                        logger.debug("No differences detected")
                        continue
            self._client.modify(service, namespace=self.namespace)

    def _create_or_update_routes(self, routes):
        for route in routes:
            name = route['metadata']['name']
            try:
                existing_route = self._client.routes(namespace=self.namespace).by_name(name)
            except KubeRequestError:
                logger.debug("Creating route {}".format(name))
                logger.debug(json.dumps(route, indent=4))
                self._client.create(route, namespace=self.namespace)
                continue

            logger.debug("Found existing route:")
            logger.debug(json.dumps(existing_route, indent=4))
            labels = dict_in_dict(route['metadata'].get('labels'),
                                  existing_route['metadata'].get('labels', {}))
            if not labels:
                logger.debug("Labels are different")
                logger.debug(json.dumps(route['metadata'].get('labels'), indent=4))
            else:
                to = dict_in_dict(route.get('spec', {}).get('to', {}),
                                  existing_route.get('spec', {}).get('to', {}))
                if not to:
                    logger.debug("To is different")
                    logger.debug(json.dumps(route.get('spec', {}).get('to', {}), indent=4))
                elif route.get('spec', {}).get('targetPort') != existing_route.get('spec', {}).get('targetPort'):
                    logger.debug("targePort {} is different".format(route.get('spec', {}).get('targetPort')))
                else:
                    logger.debug("No differences detected")
                    continue
            self._client.modify(route, namespace=self.namespace)

    def _create_or_update_deployments(self, deployments):
        for deployment in deployments:
            name = deployment['metadata']['name']
            try:
                existing_deployment = self._client.deployments(namespace=self.namespace).by_name(name)
            except KubeRequestError:
                logger.debug("Creating deployment {}".format(name))
                logger.debug(json.dumps(deployment, indent=4))
                self._client.create(deployment, namespace=self.namespace)
                continue

            logger.debug("Found existing deployment:")
            logger.debug(json.dumps(existing_deployment, indent=4))
            labels = dict_in_dict(deployment['metadata'].get('labels'),
                                  existing_deployment['metadata'].get('labels', {}))
            if not labels:
                logger.debug("Labels are different")
                logger.debug(json.dumps(deployment['metadata'].get('labels'), indent=4))
            else:
                template_labels = dict_in_dict(deployment['spec']['template']['metadata'].get('labels', {}),
                                               existing_deployment['spec']['template']['metadata'].get('labels', {}))
                if not template_labels:
                    logger.debug("Template labels are different")
                    logger.debug(json.dumps(deployment['spec']['template']['metadata'].get('labels', {}), indent=4))
                else:
                    containers = list_of_dicts_in_list_of_dicts(
                        deployment['spec']['template']['spec'].get('containers'),
                        existing_deployment['spec']['template']['spec'].get('containers')
                    )
                    if not containers:
                        logger.debug("Containers are different")
                        logger.debug(json.dumps(deployment['spec']['template']['spec'].get('containers', []), indent=4))
                    elif deployment['spec']['replicas'] != existing_deployment['spec']['replicas']:
                        logger.debug("Replicas {} is different".format(deployment['spec']['replicas']))
                    elif deployment['spec']['strategy']['type'] != existing_deployment['spec']['strategy']['type']:
                        logger.debug("Strategy {} is different".format(deployment['spec']['strategy']['type']))
                    else:
                        logger.debug("No differences detected")
                        continue
                self._client.modify(deployment, namespace=self.namespace)

    def _create_or_update_pvcs(self, pvcs):
        pass


def dict_in_dict(a, b):
    '''
    Test if a in b
    :param a: dict
    :param b: dict
    :return: bool
    '''
    if a and not b:
        return False
    if not a:
        return True
    result = True
    for key, config in a.items():
        if isinstance(config, dict):
            if dict_in_dict(config, b.get(key)):
                continue
        elif isinstance(config, list):
            if len(config) > 0 and isinstance(config[0], dict):
                if list_of_dicts_in_list_of_dicts(config, b.get(key)):
                    continue
            elif len(config) > 0:
                if set(config) in set(b.get(key, [])):
                    continue
        elif str(config) == str(b.get(key, '')):
            continue
        if isinstance(config, dict) or isinstance(config, list):
            logger.debug("{} is different".format(key))
            logger.debug(json.dumps(config, indent=4))
        else:
            logger.debug("{}: {} is different".format(key, config))
        result = False
        break
    return result


def list_of_dicts_in_list_of_dicts(a, b):
    '''
    Test if a in b
    :param a: list of dicts
    :param b: list of dicts
    :return: bool
    '''
    if a and not b:
        return False
    if not a:
        return True
    result = True
    for item_a in a:
        found = False
        for item_b in b:
            if dict_in_dict(item_a, item_b):
                found = True
                break
        if not found:
            result = False
            break
    return result

# def dict_in_dict(a, b):
#     '''
#     if dict a in dict b, return True
#     :param a: dict
#     :param b: dict
#     :return: bool
#     '''
#     if a and not b:
#         return False
#     if not a:
#         return True
#     result = True
#     for key, value in a.items():
#         if b.get(key) != value:
#             result = False
#             break
#     return result


# def ports_in_ports(a, b):
#     '''
#     If list of dicts a in list of dicts b, return True
#     :param a: list of dicts
#     :param b: list of dicts
#     :return: bool
#     '''
#     if a and not b:
#         return False
#     if not a:
#         return True
#     result = True
#     for port_a in a:
#         found = False
#         for port_b in b:
#             match = True
#             for key in port_a.keys():
#                 if port_a[key] != port_b.get(key):
#                     match = False
#                     break
#             if match:
#                 found = True
#                 break
#         if not found:
#             result = False
#             break
#     return result
