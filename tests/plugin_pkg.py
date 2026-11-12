"""The package the backend and the agent tool really run: ``pixelhq_plugin`` (loaded once per process)."""


def package():
    from dashboard import plugin_api

    return plugin_api._PACKAGE
