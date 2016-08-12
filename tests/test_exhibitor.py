from unittest.mock import MagicMock
from bubuku.zookeeper.exhibior import AWSExhibitorAddressProvider


def test_get_latest_address():
    amazon = MagicMock()
    amazon.get_addresses_by_lb_name = MagicMock(return_value=['aws-lb-1', 'aws-lb-2'])
    AWSExhibitorAddressProvider._query_exhibitors = MagicMock(return_value={'servers':['aws-lb-1-new'], 'port': 99})

    address_provider = AWSExhibitorAddressProvider(amazon, 'zk-stack-name')
    actual_result = address_provider.get_latest_address()

    assert actual_result == (['aws-lb-1-new'], 99)


def test_get_latest_address_no_exhibitors():
    amazon = MagicMock()
    amazon.get_addresses_by_lb_name = MagicMock(return_value=['aws-lb-1', 'aws-lb-2'])
    AWSExhibitorAddressProvider._query_exhibitors = MagicMock(return_value=None)

    address_provider = AWSExhibitorAddressProvider(amazon, 'zk-stack-name')
    actual_result = address_provider.get_latest_address()

    assert actual_result is None


def test_get_latest_address_2():
    amazon = MagicMock()
    amazon.get_addresses_by_lb_name = MagicMock(return_value=['aws-lb-1', 'aws-lb-2'])
    AWSExhibitorAddressProvider._query_exhibitors = MagicMock()
    AWSExhibitorAddressProvider._query_exhibitors.side_effect = [None, {'servers':['aws-lb-1-new'], 'port': 99}]

    address_provider = AWSExhibitorAddressProvider(amazon, 'zk-stack-name')
    actual_result = address_provider.get_latest_address()

    assert AWSExhibitorAddressProvider._query_exhibitors.call_count == 2
    assert actual_result == (['aws-lb-1-new'], 99)