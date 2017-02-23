import logging

import click
import requests
from requests import Response

from bubuku.config import load_config, KafkaProperties, Config
from bubuku.env_provider import EnvProvider
from bubuku.features.remote_exec import RemoteCommandExecutorCheck
from bubuku.zookeeper import load_exhibitor_proxy, BukuExhibitor

_LOG = logging.getLogger('bubuku.cli')


def _print_table(table: list, print_function=None):
    if not print_function:
        print_function = print
    names = sorted(set([v for v in sum([list(k.keys()) for k in table], [])]))
    lengths = {n: len(n) for n in names}
    for d in table:
        for k, v in d.items():
            if lengths[k] < len(str(v)):
                lengths[k] = len(str(v))
    format_string = '  '.join(['{!s:' + str(lengths[n]) + 's}' for n in names])
    print_function(format_string.format(*names))
    for item in table:
        print_function(format_string.format(*[item.get(n, '') for n in names]))


def __validate_not_empty(ctx, param, value):
    if not value:
        raise click.BadParameter('Parameter must have value')


def __get_opt_broker_id(broker_id: str, config: Config, zk: BukuExhibitor, env_provider: EnvProvider) -> str:
    if not broker_id:
        kafka_properties = KafkaProperties(config.kafka_settings_template, '/tmp/tmp.props'.format(config.kafka_dir))
        broker_id_manager = env_provider.create_broker_id_manager(zk, kafka_properties)
        broker_id = broker_id_manager.detect_broker_id()
        _LOG.info('Will use broker_id {}'.format(broker_id))
    running_brokers = zk.get_broker_ids()
    if broker_id not in running_brokers:
        raise Exception('Broker id {} is not registered ({}), can not restart'.format(broker_id, running_brokers))
    return broker_id


def __prepare_configs():
    config = load_config()
    _LOG.info('Using config: {}'.format(config))
    env_provider = EnvProvider.create_env_provider(config)
    return config, env_provider


logging.basicConfig(level=getattr(logging, 'INFO', None))


@click.group()
def cli():
    pass


@cli.command('restart', help='Restart kafka instance')
@click.option('--broker', type=click.STRING,
              help='Broker id to restart. By default current broker id is restarted')
def restart_broker(broker: str):
    config, env_provider = __prepare_configs()
    with load_exhibitor_proxy(env_provider.get_address_provider(), config.zk_prefix) as zookeeper:
        broker_id = __get_opt_broker_id(broker, config, zookeeper, env_provider)
        RemoteCommandExecutorCheck.register_restart(zookeeper, broker_id)


@cli.command('rebalance', help='Run rebalance process on one of brokers')
@click.option('--broker', type=click.STRING,
              help="Broker instance on which to perform rebalance. By default, any free broker will start it")
@click.option('--exclude_brokers', type=click.STRING,
              help="Comma-separated list of brokers to exclude from rebalance (they will be emptied)")
@click.option('--exclude_topics', type=click.STRING, help="Comma-separated list of topics to exclude from rebalance")
def rebalance_partitions(broker: str, exclude_brokers: str, exclude_consumer_offsets: str):
    config, env_provider = __prepare_configs()
    with load_exhibitor_proxy(env_provider.get_address_provider(), config.zk_prefix) as zookeeper:
        broker_id = __get_opt_broker_id(broker, config, zookeeper, env_provider) if broker else None
        RemoteCommandExecutorCheck.register_rebalance(zookeeper, broker_id, exclude_brokers.split(','),
                                                      exclude_consumer_offsets.split(','))


@cli.command('migrate', help='Replace one broker with another for all partitions')
@click.option('--from', 'from_', type=click.STRING, callback=__validate_not_empty,
              help='List of brokers to migrate from (separated with ",")')
@click.option('--to', type=click.STRING, callback=__validate_not_empty,
              help='List of brokers to migrate to (separated with ",")')
@click.option('--shrink', is_flag=True, default=False, show_default=True,
              help='Whether or not to shrink replaced broker ids form partition assignment')
@click.option('--broker', type=click.STRING, help='Optional broker id to execute check on')
def migrate_broker(from_: str, to: str, shrink: bool, broker: str):
    config, env_provider = __prepare_configs()
    with load_exhibitor_proxy(env_provider.get_address_provider(), config.zk_prefix) as zookeeper:
        broker_id = __get_opt_broker_id(broker, config, zookeeper, env_provider) if broker else None
        RemoteCommandExecutorCheck.register_migration(zookeeper, from_.split(','), to.split(','), shrink, broker_id)


@cli.command('swap_fat_slim', help='Move one partition from fat broker to slim one')
@click.option('--threshold', type=click.INT, default="100000", show_default=True, help="Threshold in kb to run swap")
def swap_partitions(threshold: int):
    config, env_provider = __prepare_configs()
    with load_exhibitor_proxy(env_provider.get_address_provider(), config.zk_prefix) as zookeeper:
        RemoteCommandExecutorCheck.register_fatboy_slim(zookeeper, threshold_kb=threshold)


@cli.group(name='actions', help='Work with running actions')
def actions():
    pass


@actions.command('list', help='List all the actions on broker(s)')
@click.option('--broker', type=click.STRING,
              help='Broker id to list actions on. By default all brokers are enumerated')
def list_actions(broker: str):
    table = []
    config, env_provider = __prepare_configs()

    for broker_id, address in _list_broker_addresses(config, env_provider, broker):
        try:
            response = requests.get('http://{}:{}/api/controller/queue'.format(address, config.health_port))
        except Exception as e:
            print('Failed to query information on {} ({})'.format(broker_id, address))
            _LOG.error('Failed to query information on {} ({})'.format(broker_id, address), exc_info=e)
            continue
        line = {
            '_broker_id': broker_id,
            '_broker_address': address,
        }
        if response.status_code != 200:
            line['error'] = _extract_error(response)
            table.append(line)
        else:
            changes = response.json()
            if not changes:
                line.update({
                    'type': None,
                    'description': None,
                    'running': None
                })
                table.append(line)
            else:
                for change in changes:
                    line_copy = dict(line)
                    line_copy.update(change)
                    table.append(line_copy)
    if not table:
        print('No brokers found')
    else:
        _print_table(table)


@actions.command('delete', help='Remove all actions of specified type on broker(s)')
@click.option('--action', type=click.STRING,
              help='Action to delete')
@click.option('--broker', type=click.STRING,
              help='Broker id to delete actions on. By default actions are deleted on all brokers')
def delete_actions(action: str, broker: str):
    if not action:
        print('No action specified. Please specify it')
    config, env_provider = __prepare_configs()

    for broker_id, address in _list_broker_addresses(config, env_provider, broker):
        try:
            response = requests.delete('http://{}:{}/api/controller/queue/{}'.format(address, config.health_port, action))
        except Exception as e:
            print('Failed to query information on {} ({})'.format(broker_id, address))
            _LOG.error('Failed to query information on {} ({})'.format(broker_id, address), exc_info=e)
            continue
        if response.status_code not in (200, 204):
            print('Failed to delete action from {} ({}): {}'.format(broker, address, _extract_error(response)))
        else:
            print('Removed action {} from {} ({})'.format(action, broker_id, address))


def _extract_error(response: Response):
    try:
        return response.json()['message']
    except Exception as e:
        _LOG.error('Failed to parse response message', exc_info=e)
        return response.text()


def _list_broker_addresses(config, env_provider, broker):
    with load_exhibitor_proxy(env_provider.get_address_provider(), config.zk_prefix) as zookeeper:
        for broker_id in zookeeper.get_broker_ids():
            if broker and broker != broker_id:
                continue
            yield broker_id, zookeeper.get_broker_address(broker_id)


@cli.command('stats', help='Display statistics about brokers')
def show_stats():
    config, env_provider = __prepare_configs()
    with load_exhibitor_proxy(env_provider.get_address_provider(), config.zk_prefix) as zookeeper:
        disk_stats = zookeeper.get_disk_stats()
        table = []
        for broker_id in zookeeper.get_broker_ids():
            disk = disk_stats.get(broker_id, {}).get('disk') if disk_stats else {}
            table.append({
                'Broker Id': broker_id,
                'Address': zookeeper.get_broker_address(broker_id),
                'Free kb': disk.get('free_kb'),
                'Used kb': disk.get('used_kb')
            })
        _print_table(table)


@cli.command('runfaster', help='Rebalance load on kafka nodes')
def run_faster():
    config, env_provider = __prepare_configs()
    with load_exhibitor_proxy(env_provider.get_address_provider(), config.zk_prefix) as ex:
        def get_broker_ids_sorted_by_load(broker_ids) -> []:
            load_by_broker = {
                id_: float(requests.get(
                    ':8778/jolokia/read/java.lang:type=OperatingSystem'.format(ex.get_broker_address(id_))).json()[
                               'value']['SystemCpuLoad'])
                for id_ in broker_ids
                }
            print('Brokers load: {}'.format(load_by_broker))
            return sorted(broker_ids, key=lambda id_: load_by_broker[id_])

        def get_topics_load_sorted(broker_id, tps) -> dict:
            ip = ex.get_broker_address(broker_id)
            load_dict = {}
            for topic, partition in tps:
                if topic in load_dict:
                    continue
                load_dict[topic] = requests.get(
                    '{}:8778/jolokia/read/kafka.server:name=MessagesInPerSec,type=BrokerTopicMetrics,topic={}'
                        .format(ip, topic)).json()['value']['OneMinuteRate']
            return sorted(tps, key=lambda tp: load_dict.get(tp[0]))

        def select_swap_candidate(loaded_tps, not_loaded_tps) -> tuple:  # topic partition
            for i in range(0, len(loaded_tps) // 10):
                candidate = loaded_tps[len(loaded_tps) - 1]
                if candidate in not_loaded_tps:
                    return candidate

        tp_to_brokers = {}
        leadership_broker_to_tp_list = {}
        for topic, partition, brokers in ex.load_partition_assignment():
            tp = (topic, partition)
            tp_to_brokers[tp] = brokers

            leader = brokers[0]
            if leader not in leadership_broker_to_tp_list:
                leadership_broker_to_tp_list[leader] = []
            leadership_broker_to_tp_list[leader].append(tp)
        load_by_leader = {}
        for leader, tps in leadership_broker_to_tp_list.items():
            load_by_leader[leader] = get_topics_load_sorted(leader, tps)
        load_ordered = get_broker_ids_sorted_by_load()
        loaded = load_ordered[len(load_ordered) - 1]
        for not_loaded in load_ordered[:len(load_ordered) // 2]:
            candidate = select_swap_candidate(load_by_leader[loaded], load_by_leader[not_loaded])
            if candidate:
                broker_ids = tp_to_brokers[candidate]
                print('old allocation for {}: {}'.format(candidate, broker_ids))
                length = len(broker_ids)
                del broker_ids[not_loaded]
                broker_ids = [not_loaded] + broker_ids
                if length != len(broker_ids):
                    raise Exception('broker ids length changed')
                print('New allocation for candidate {}: {}'.format(candidate, broker_ids))
                # ex.reallocate_partition(candidate[0], candidate[1], broker_ids)
                return

if __name__ == '__main__':
    cli()
