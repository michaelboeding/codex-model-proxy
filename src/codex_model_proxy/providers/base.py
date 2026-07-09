from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderModel:
    slug: str
    display_name: str
    aliases: tuple[str, ...] = ()
    description: str | None = None


@dataclass(frozen=True)
class ProviderSpec:
    backend_id: str
    route_prefix: str
    display_name: str
    default_model: str
    models: tuple[ProviderModel, ...]
    owned_by: str
    catalog_description: str
    comp_hash: str
    runner_description: str
    requires_auth_env: tuple[str, ...] = ()

    @property
    def available_model_ids(self) -> list[str]:
        return [model.slug for model in self.models]

    @property
    def aliases(self) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for model in self.models:
            aliases[model.slug] = model.slug
            for alias in model.aliases:
                aliases[alias] = model.slug
        return aliases

    def route_id(self, model: str) -> str:
        return f"{self.route_prefix}:{model}"

    def resolve_local_model(self, requested_model: object) -> str | None:
        requested = str(requested_model or "").strip()
        if not requested:
            return None
        return self.aliases.get(requested)

    def display_name_for(self, slug: str) -> str:
        for model in self.models:
            if model.slug == slug:
                return model.display_name
        return slug.replace("-", " ").replace("_", " ").title().replace("Cli", "CLI")


@dataclass(frozen=True)
class ModelRoute:
    route_id: str
    provider: ProviderSpec
    model: str

    @property
    def display_name(self) -> str:
        return f"{self.provider.display_name} {self.provider.display_name_for(self.model)}"
