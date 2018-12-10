import logging

from bubuku.aws import AWSResources
from bubuku.aws.cluster_config import ClusterConfig

_LOG = logging.getLogger('bubuku.aws.security_group')


def create_or_ger_security_group(aws_: AWSResources, cluster_config: ClusterConfig) -> dict:
    _LOG.info('Configuring security group ...')
    security_groups = aws_.ec2_client.describe_security_groups(
        Filters=[{'Name': 'group-name', 'Values': [cluster_config.get_cluster_name()]}])
    if security_groups['SecurityGroups']:
        sg = security_groups['SecurityGroups'][0]
        _LOG.info('Security group for %s exists, will use it %s', cluster_config.get_cluster_name(), sg['GroupId'])
        return sg

    _LOG.info("Security group does not exists, creating ...")
    sg_name = cluster_config.get_cluster_name()
    sg = aws_.ec2_client.create_security_group(
        GroupName=sg_name,
        VpcId=cluster_config.get_vpc_id(),
        Description='Bubuku Security Group')
    _LOG.info("Security group %s is created", sg_name)
    aws_.ec2_client.create_tags(Resources=[sg['GroupId']], Tags=[{'Key': 'Name', 'Value': sg_name}])
    aws_.ec2_client.authorize_security_group_ingress(
        GroupId=sg['GroupId'],
        IpPermissions=[get_ip_permission(22), get_ip_permission(8004),
                       get_ip_permission(8778), get_ip_permission(9100),
                       get_ip_permission(9092),
                       get_ip_permission(cluster_config.get_health_port())])
    _LOG.info("Security group got ingress for ports: 22, 8004, 8080, 8778, 9100, %s", cluster_config.get_health_port())
    return sg


def get_ip_permission(port: int):
    return {
        'IpProtocol': 'tcp',
        'FromPort': port,
        'ToPort': port,
        'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
    }
