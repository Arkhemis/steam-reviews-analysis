import dagster as dg

from orchestration.steam.events import SteamEventsConfig

steam_events_full_refresh_job = dg.define_asset_job(
    name="steam_events_full_refresh",
    selection=dg.AssetSelection.assets("steam_events"),
    description="Rescanne l'historique complet des annonces Steam.",
    config=dg.RunConfig(ops={"steam_events": SteamEventsConfig(full_refresh=True)}),
)


__all__ = [
    "steam_events_full_refresh_job",
]
