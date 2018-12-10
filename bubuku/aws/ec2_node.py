import copy
import logging
import time

import yaml

from bubuku.aws import volume, AWSResources, taupage, metric, subnet, security_group, iam
from bubuku.aws.cluster_config import ClusterConfig

_LOG = logging.getLogger('bubuku.aws.ec2_node')


class EC2(object):
    def __init__(self, aws: AWSResources):
        self.aws = aws

    def _create_tagged_volume(self, cluster_config: ClusterConfig, zone: str, name: str):
        _LOG.info('Creating EBS volume %s in %s', name, zone)
        vol = self.aws.ec2_client.create_volume(
            AvailabilityZone=zone,
            VolumeType=cluster_config.get_volume_type(),
            Size=cluster_config.get_volume_size(),
            Encrypted=False,
        )
        _LOG.info('%s is successfully created', vol['VolumeId'])

        _LOG.info('Tagging %s with Taupage:erase-on-boot, to format only once', vol['VolumeId'])
        tags = [
            {
                'Key': 'Name',
                'Value': name
            }, {
                'Key': 'Taupage:erase-on-boot',
                'Value': 'True'
            }
        ]
        self.aws.ec2_client.create_tags(Resources=[vol['VolumeId']], Tags=tags)

    def _launch_instance(self, cluster_config: ClusterConfig, ip: str, subnet_: dict, ami: object,
                         security_group_id: str, iam_profile):
        _LOG.info('Launching node %s in %s', ip, subnet_['AvailabilityZone'])

        #
        # Override any ephemeral volumes with NoDevice mapping,
        # otherwise auto-recovery alarm cannot be actually enabled.
        #
        _LOG.info('Overriding ephemeral volumes to be able to set up AWS auto recovery alarm ')
        block_devices = []
        for bd in ami.block_device_mappings:
            if 'Ebs' in bd:
                #
                # This has to be our root EBS.
                #
                # If the Encrypted flag is present, we have to delete
                # it even if it matches the actual snapshot setting,
                # otherwise amazon will complain rather loudly.
                #
                # Take a deep copy before deleting the key:
                #
                bd = copy.deepcopy(bd)

                root_ebs = bd['Ebs']
                if 'Encrypted' in root_ebs:
                    del (root_ebs['Encrypted'])

                block_devices.append(bd)
            else:
                # ignore any ephemeral volumes (aka. instance storage)
                block_devices.append({
                    'DeviceName': bd['DeviceName'],
                    'NoDevice': ''
                })

        if cluster_config.should_create_ebs():
            self._create_tagged_volume(cluster_config, subnet_['AvailabilityZone'], volume.KAFKA_LOGS_EBS)

        user_data = cluster_config.get_user_data()
        user_data['volumes']['ebs']['/dev/xvdk'] = volume.KAFKA_LOGS_EBS
        taupage_user_data = '#taupage-ami-config\n{}'.format(yaml.safe_dump(user_data))

        resp = self.aws.ec2_client.run_instances(
            ImageId=ami.id,
            MinCount=1,
            MaxCount=1,
            SecurityGroupIds=[security_group_id],
            UserData=taupage_user_data,
            InstanceType=cluster_config.get_instance_type(),
            SubnetId=subnet_['SubnetId'],
            PrivateIpAddress=ip,
            BlockDeviceMappings=block_devices,
            IamInstanceProfile={'Arn': iam_profile['Arn']},
            DisableApiTermination=False,
            EbsOptimized=True)

        instance_id = resp['Instances'][0]['InstanceId']
        _LOG.info('Instance %s launched, waiting for it to initialize', instance_id)
        self.aws.ec2_client.create_tags(
            Resources=[instance_id],
            Tags=[
                {'Key': 'Name', 'Value': cluster_config.get_cluster_name()},
                {'Key': 'StackName', 'Value': cluster_config.get_cluster_name()}
            ]
        )

        return instance_id

    def _launch_nodes(self, cluster_config: ClusterConfig, node_ips: list, taupage_amis, security_groups, iam_profile):
        starting_instances = []
        for subnet_, ip in node_ips:
            starting_instances.append(
                self._launch_instance(
                    cluster_config,
                    ip,
                    subnet_,
                    taupage_amis,
                    security_groups['GroupId'],
                    iam_profile))
            # wait for all instances to start
        while starting_instances:
            _LOG.info("Waiting for instances to start: {}".format(starting_instances))
            time.sleep(5)
            resp = self.aws.ec2_client.describe_instances(InstanceIds=starting_instances)
            started_instances = []
            for r in resp['Reservations']:
                started_instances += [i['InstanceId'] for i in r['Instances'] if i['State']['Name'] != 'pending']
            if started_instances:
                _LOG.info('Instances {} started'.format(started_instances))
            for instance_id in started_instances:
                starting_instances.remove(instance_id)
                metric.create_auto_recovery_alarm(self.aws, cluster_config.get_cluster_name(), instance_id)

    def create(self, cluster_config: ClusterConfig, instance_count: int):
        _LOG.info('Preparing AWS configuration for ec2 instance creation')
        try:
            node_ips = subnet.allocate_ip_addresses(self.aws, cluster_config, instance_count)
            taupage_amis = taupage.find_amis(self.aws.ec2_resource, self.cluster_config.get_aws_region())
            security_groups = security_group.create_or_ger_security_group(self.aws, cluster_config)
            iam_profile = iam.create_or_get_instance_profile(self.aws, cluster_config)

            self._launch_nodes(cluster_config, node_ips, taupage_amis, security_groups, iam_profile)

        except Exception as e:
            _LOG.error('''
                    You were trying to deploy Bubuku, but the process has failed :-(
                    
                    One of the reasons might be that some of Private IP addresses we were
                    going to use to launch the EC2 instances were taken by some other
                    instances in the middle of the process.  If that is the case, simply
                    retrying the operation might resolve the problem (you still might need
                    to clean up after this attempt before retrying).
                    
                    Please review the error message to see if that is the case, then
                    either correct the error or retry.
                    
                ''')
            raise e
