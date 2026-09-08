import dagster as dg

from orchestration.steam.census import SteamCensusConfig
from orchestration.steam.events import SteamEventsConfig

steam_census_full_refresh_job = dg.define_asset_job(
    name="steam_census_full_refresh",
    selection=dg.AssetSelection.assets("steam_review_counts"),
    description="Sonde tous les jeux Steam, hors fréquence par jeu et hors plafond.",
    config=dg.RunConfig(
        ops={"steam_review_counts": SteamCensusConfig(full_refresh=True)}
    ),
)

steam_events_full_refresh_job = dg.define_asset_job(
    name="steam_events_full_refresh",
    selection=dg.AssetSelection.assets("steam_events"),
    description="Rescanne l'historique complet des annonces Steam.",
    config=dg.RunConfig(ops={"steam_events": SteamEventsConfig(full_refresh=True)}),
)


__all__ = [
    "steam_census_full_refresh_job",
    "steam_events_full_refresh_job",
]
