import requests
import yaml

_ARTIFACT_NAME = 'bubuku-appliance'


class ConfigLoader():
    def load_config(self) -> dict:
        pass


class AwsInstanceUserDataLoader(ConfigLoader):
    def load_config(self):
        return yaml.load(requests.get('http://169.254.169.254/latest/user-data').text)


class ClusterConfig():

    def __init__(self, config_loader: ConfigLoader):
        self._user_data = config_loader.load_config()
        self._env_vars = self._user_data.get('environment')

    def get_cluster_name(self):
        return self._env_vars.get('CLUSTER_NAME')

    def get_health_port(self):
        return self._env_vars.get('HEALTH_PORT')

    def get_aws_region(self):
        return 'eu-central-1'

    def get_instance_type(self):
        return self._user_data.get('instance_type')

    def set_scalyr_account_key(self, scalyr_account_key):
        self._user_data['scalyr_account_key'] = scalyr_account_key

    def set_scalyr_region(self, scalyr_region):
        self._user_data['scalyr_region'] = scalyr_region

    def set_application_version(self, image):
        self._user_data['application_version'] = image
        self._user_data['source'] = 'registry.opensource.zalan.do/aruha/{}:{}'.format(_ARTIFACT_NAME, image)

    def get_application_version(self):
        return self._user_data.get('application_version')

    def set_instance_type(self, instance_type):
        self._user_data['instance_type'] = instance_type

    def set_kms_key_id(self, kms_key_id):
        self._user_data['kms_key_id'] = kms_key_id

    def get_kms_key_id(self):
        return self._user_data.get("kms_key_id")

    def get_availability_zone(self):
        return self._user_data.get('availability_zone')

    def set_availability_zone(self, v):
        self._user_data['availability_zone'] = v

    def should_create_ebs(self):
        return self._user_data.get('should_create_ebs')

    def set_should_create_ebs(self, v):
        self._user_data['should_create_ebs'] = v

    def get_volume_size(self):
        return self._user_data.get('volume_size')

    def set_volume_size(self, v):
        self._user_data['volume_size'] = v

    def get_volume_type(self):
        return self._user_data.get('volume_type')

    def set_volume_type(self, v):
        self._user_data['volume_type'] = v

    def get_vpc_id(self):
        return self._user_data.get('vpc_id')

    def set_vpc_id(self, v):
        self._user_data['vpc_id'] = v

    def get_user_data(self):
        return dict(self._user_data)
