from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProviderModel:
    slug: str
    display_name: str
    aliases: tuple[str, ...] = ()
    description: str | None = None


@dataclass(frozen=True)
class ProviderSpec:
    backend_id: str
    codex_provider_id: str
    display_name: str
    stable_model: str
    default_model: str
    models: tuple[ProviderModel, ...]
    active_model_file: Path
    owned_by: str
    catalog_description: str
    comp_hash: str
    runner_description: str

    @property
    def available_model_ids(self) -> list[str]:
        return [model.slug for model in self.models]

    @property
    def catalog_model_ids(self) -> list[str]:
        names = [self.stable_model]
        for model in self.models:
            if model.slug not in names:
                names.append(model.slug)
        return names

    @property
    def aliases(self) -> dict[str, str]:
        aliases = {self.stable_model: self.stable_model}
        for model in self.models:
            aliases[model.slug] = model.slug
            for alias in model.aliases:
                aliases[alias] = model.slug
        return aliases

    def resolve_model(self, requested_model: object, active_model: str) -> str:
        requested = str(requested_model or self.stable_model).strip()
        if not requested:
            return active_model
        resolved = self.aliases.get(requested)
        if resolved == self.stable_model:
            return active_model
        if resolved:
            return resolved
        return active_model

    def display_name_for(self, slug: str) -> str:
        if slug == self.stable_model:
            return self.display_name
        for model in self.models:
            if model.slug == slug:
                return model.display_name
        return slug.replace("-", " ").replace("_", " ").title().replace("Cli", "CLI")
