"""Small validation helpers; schema meaning remains in each application."""

from .errors import UpdateError
from .postgres import PostgresResource
from .resources import TreeResource
from .wire import digest, dumps


def check_resources(resources, trees, databases=()):
    if set(resources) != set(trees) | set(databases):
        raise UpdateError("invalid_profile")
    if any(not isinstance(resources[name], TreeResource) for name in trees) or any(
        not isinstance(resources[name], PostgresResource) for name in databases
    ):
        raise UpdateError("invalid_profile")


def configuration_revision(resources, names=("configuration",)):
    return digest(dumps({name: resources[name].inventory() for name in names}))
