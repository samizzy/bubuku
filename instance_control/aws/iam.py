import json
import logging
import time

from botocore.exceptions import ClientError

from instance_control.aws import AWSResources

_LOG = logging.getLogger('bubuku.cluster.aws.iam')


def create_or_get_instance_profile(aws_: AWSResources, cluster_config: dict):
    profile_name = 'profile-{}'.format(cluster_config['cluster_name'])

    try:
        profile = aws_.iam_client.get_instance_profile(InstanceProfileName=profile_name)
        _LOG.info("IAM profile %s exists, using it", profile_name)
        return profile['InstanceProfile']
    except ClientError:
        _LOG.info("IAM profile %s does not exists, creating ...", profile_name)
        pass

    profile = aws_.iam_client.create_instance_profile(InstanceProfileName=profile_name)

    role_name = 'role-{}'.format(cluster_config['cluster_name'])
    _LOG.info("Creating iam role %s", role_name)
    aws_.iam_client.create_role(RoleName=role_name, AssumeRolePolicyDocument="""{
        "Version": "2012-10-17",
        "Statement": [{
             "Action": "sts:AssumeRole",
             "Effect": "Allow",
             "Principal": {
                 "Service": "ec2.amazonaws.com"
             }
        }]
    }""")

    policy_datavolume_document = """{
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "ec2:DescribeTags",
                    "ec2:DeleteTags",
                    "ec2:DescribeVolumes",
                    "ec2:AttachVolume"
                ],
                "Resource": "*"
            }
        ]
    }"""
    policy_metadata_document = """{
        "Version": "2012-10-17",
        "Statement": [
            {
                "Action": "ec2:Describe*",
                "Resource": "*",
                "Effect": "Allow"
            },
            {
                "Action": "elasticloadbalancing:Describe*",
                "Resource": "*",
                "Effect": "Allow"
            }
        ]
    }"""
    policy_zmon_document = """{
        "Version": "2012-10-17",
        "Statement": [
            {
                "Action": "cloudwatch:PutMetricData",
                "Resource": "*",
                "Effect": "Allow"
            }
        ]
    }"""

    policy_cw_document = """{
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "VisualEditor0",
                "Effect": "Allow",
                "Action": [
                    "cloudwatch:PutMetricAlarm",
                    "cloudwatch:DeleteAlarms"
                ],
                "Resource": "*"
            }
        ]
    }"""

    policy_ec2_document = """{
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "VisualEditor0",
                "Effect": "Allow",
                "Action": [
                    "ec2:DetachVolume",
                    "ec2:AttachVolume",
                    "ec2:AuthorizeSecurityGroupIngress",
                    "ec2:DescribeInstances",
                    "ec2:TerminateInstances",
                    "ec2:DeleteTags",
                    "ec2:DescribeTags",
                    "ec2:CreateTags",
                    "ec2:DescribeInstanceAttribute",
                    "ec2:RunInstances",
                    "ec2:StopInstances",
                    "ec2:DescribeSecurityGroups",
                    "ec2:DescribeVolumeAttribute",
                    "ec2:CreateVolume",
                    "ec2:DescribeImages",
                    "ec2:DescribeVolumeStatus",
                    "ec2:StartInstances",
                    "ec2:CreateSecurityGroup",
                    "ec2:DescribeVolumes",
                    "ec2:DescribeSubnets",
                    "ec2:DescribeInstanceStatus"
                ],
                "Resource": "*"
            }
        ]
    }"""

    policy_iam_document = """{
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "VisualEditor0",
                "Effect": "Allow",
                "Action": [
                    "iam:CreateInstanceProfile",
                    "iam:PassRole",
                    "iam:GetInstanceProfile",
                    "iam:CreateRole",
                    "iam:PutRolePolicy",
                    "iam:AddRoleToInstanceProfile"
                ],
                "Resource": "*"
            }
        ]
    }"""

    policy_datavolume = 'policy-{}-datavolume'.format(cluster_config['cluster_name'])
    _LOG.info("Creating IAM policy %s", policy_datavolume)
    aws_.iam_client.put_role_policy(RoleName=role_name,
                                    PolicyName=policy_datavolume,
                                    PolicyDocument=policy_datavolume_document)

    policy_metadata = 'policy-{}-metadata'.format(cluster_config['cluster_name'])
    _LOG.info("Creating IAM policy %s", policy_metadata)
    aws_.iam_client.put_role_policy(RoleName=role_name,
                                    PolicyName=policy_metadata,
                                    PolicyDocument=policy_metadata_document)

    policy_zmon = 'policy-{}-zmon'.format(cluster_config['cluster_name'])
    _LOG.info("Creating IAM policy %s", policy_zmon)
    aws_.iam_client.put_role_policy(RoleName=role_name,
                                    PolicyName=policy_zmon,
                                    PolicyDocument=policy_zmon_document)

    policy_cw = 'policy-{}-cw'.format(cluster_config['cluster_name'])
    _LOG.info("Creating IAM policy %s", policy_cw)
    aws_.iam_client.put_role_policy(RoleName=role_name,
                                    PolicyName=policy_cw,
                                    PolicyDocument=policy_cw_document)

    policy_ec2 = 'policy-{}-ec2'.format(cluster_config['cluster_name'])
    _LOG.info("Creating IAM policy %s", policy_zmon)
    aws_.iam_client.put_role_policy(RoleName=role_name,
                                    PolicyName=policy_ec2,
                                    PolicyDocument=policy_ec2_document)

    policy_iam = 'policy-{}-iam'.format(cluster_config['cluster_name'])
    _LOG.info("Creating IAM policy %s", policy_zmon)
    aws_.iam_client.put_role_policy(RoleName=role_name,
                                    PolicyName=policy_iam,
                                    PolicyDocument=policy_iam_document)

    if "kms_key_id" in cluster_config:
        policy_kms_document = json.dumps({
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "kms:Decrypt",
                    "Effect": "Allow",
                    "Resource": [cluster_config["kms_key_id"]]
                }
            ]
        })
        _LOG.info("Creating IAM policy $s", policy_kms_document)
        aws_.iam_client.put_role_policy(RoleName=role_name,
                                        PolicyName='policy-{}-kms'.format(cluster_config['cluster_name']),
                                        PolicyDocument=policy_kms_document)

    aws_.iam_client.add_role_to_instance_profile(InstanceProfileName=profile_name, RoleName=role_name)

    _LOG.info("IAM profile %s is created", profile_name)

    #
    # FIXME: using an instance profile right after creating one
    # can result in 'not found' error, because of eventual
    # consistency.  For now fix with a sleep, should rather
    # examine exception and retry after some delay.
    #
    _LOG.info('Waiting 30 secs after IAM profile creation to be sure it is available')
    time.sleep(30)

    return profile['InstanceProfile']
