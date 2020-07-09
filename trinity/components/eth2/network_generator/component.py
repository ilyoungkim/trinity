from argparse import ArgumentParser, Namespace, _SubParsersAction
import json
from json import JSONDecodeError
import logging
import pathlib
import time

from eth2.genesis import (
    generate_genesis_config,
    genesis_config_from_state,
    update_genesis_config_with_time,
)
from trinity.config import BeaconChainConfig, TrinityConfig
from trinity.extensibility import Application

CREATE_NETWORK_HELP = """
Produces a genesis state and a set of private keys for validators in the genesis state
"""
CONFIG_PROFILE_HELP = """
Use this profile of configuration to determine minimal parameters in the system.
"""


class BytesJsonEncoder(json.JSONEncoder):
    def default(self, obj: object) -> str:
        if isinstance(obj, bytes):
            return obj.hex()
        return super().default(obj)


def _get_network_config_path_for(profile: str) -> pathlib.Path:
    return BeaconChainConfig.get_genesis_config_file_path(profile)


class NetworkGeneratorComponent(Application):
    """
    This component accepts some initial configuration and produces a genesis state and a set
    of private keys for validators in the genesis state.
    """

    logger = logging.getLogger("trinity.components.eth2.network_generator")

    @classmethod
    def configure_parser(
        cls, arg_parser: ArgumentParser, subparser: _SubParsersAction
    ) -> None:
        network_generator_parser = subparser.add_parser(
            "create-network", help=CREATE_NETWORK_HELP
        )
        network_generator_parser.add_argument(
            "--config-profile",
            help=CONFIG_PROFILE_HELP,
            choices=("minimal", "mainnet", "altona"),
            default="minimal",
        )
        network_generator_parser.add_argument(
            "--output", type=pathlib.Path, help="where to save the output configuration"
        )
        genesis_group = network_generator_parser.add_mutually_exclusive_group(
            required=True
        )
        genesis_group.add_argument(
            "--genesis-time", type=int, help="Unix timestamp to use as the genesis time"
        )
        genesis_group.add_argument(
            "--genesis-delay",
            type=int,
            help="Delay in seconds to use as the genesis time from time of execution",
        )
        genesis_group.add_argument(
            "--genesis-state",
            type=pathlib.Path,
            help="Path to an SSZ file that contains the initial chain state",
        )

        network_generator_parser.set_defaults(func=cls._generate_network_as_json)

    @classmethod
    def _generate_network_as_json(
        cls, args: Namespace, trinity_config: TrinityConfig
    ) -> None:
        cls.logger.info("using config profile: %s", args.config_profile)

        if args.output:
            output_file_path = args.output
        else:
            output_file_path = _get_network_config_path_for(args.config_profile)

        if output_file_path.exists():
            with open(output_file_path, "r") as config_file:
                try:
                    existing_genesis_config = json.load(config_file)
                except JSONDecodeError as e:
                    existing_genesis_config = None
                    cls.logger.warning("failed to load existing config as json: %s", e)

        if args.genesis_time:
            genesis_time = args.genesis_time
            cls.logger.info("genesis time specified from config: %d", genesis_time)
        elif args.genesis_delay:
            genesis_time = int(time.time()) + args.genesis_delay
            cls.logger.info(
                "genesis delay specified from config: %d", args.genesis_delay
            )

        if (args.genesis_time or args.genesis_delay) and existing_genesis_config:
            genesis_config = update_genesis_config_with_time(
                existing_genesis_config, genesis_time
            )
        elif args.genesis_time or args.genesis_delay:
            genesis_config = generate_genesis_config(args.config_profile, genesis_time)
        else:
            genesis_config = genesis_config_from_state(
                args.config_profile, args.genesis_state
            )

        genesis_time = genesis_config["genesis_state"]["genesis_time"]
        cls.logger.info(
            "configuration generated; genesis state has root %s with genesis time %d (%s); "
            "writing to '%s'",
            genesis_config["genesis_state_root"],
            genesis_time,
            time.strftime("%Y-%m-%d %I:%M%z", time.localtime(genesis_time)),
            output_file_path,
        )
        output_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file_path, "w") as output_file:
            json.dump(genesis_config, output_file, cls=BytesJsonEncoder)
