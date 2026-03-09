"""Entropy injection — curated external concepts to prevent convergence."""

import logging
import random
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.error import URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ── Data Model ──────────────────────────────────────────────────


class EntropyConcept(BaseModel):
    """An external concept injected to break convergence."""

    title: str
    summary: str
    source: str  # "wikipedia" or "arxiv"
    domain: str
    strategy: str  # "curated_random" | "arxiv_rotation" | "adjacent_possible"
    url: str = ""


# ── Domain Pools ────────────────────────────────────────────────

CURATED_DOMAIN_POOLS: dict[str, list[str]] = {
    "mathematics": [
        "Ergodic_theory", "Topology", "Category_theory", "Fractal",
        "Game_theory", "Chaos_theory", "Graph_theory", "Number_theory",
        "Bayesian_inference", "Information_theory", "Cellular_automaton",
        "Markov_chain", "Fourier_transform", "Non-Euclidean_geometry",
        "Gödel's_incompleteness_theorems", "Knot_theory", "Group_theory",
        "Measure_(mathematics)", "Combinatorics", "Fixed-point_theorem",
    ],
    "evolutionary_biology": [
        "Symbiogenesis", "Punctuated_equilibrium", "Kin_selection",
        "Horizontal_gene_transfer", "Red_Queen_hypothesis", "Exaptation",
        "Neutral_theory_of_molecular_evolution", "Convergent_evolution",
        "Sexual_selection", "Epigenetics", "Niche_construction",
        "Gene_flow", "Genetic_drift", "Adaptive_radiation",
        "Coevolution", "Speciation", "Phenotypic_plasticity",
        "Evolutionary_developmental_biology", "Mutualism_(biology)",
        "Altruism_(biology)",
    ],
    "architecture": [
        "Biomimetics", "Parametricism", "Metabolist_movement",
        "Arcology", "Tensegrity", "Geodesic_dome",
        "Organic_architecture", "Deconstructivism", "Brutalist_architecture",
        "Adaptive_reuse", "Vernacular_architecture", "Feng_shui",
        "Sacred_geometry", "Critical_regionalism", "Sustainable_architecture",
        "Kinetic_architecture", "Megastructure", "Anti-design",
        "Responsive_architecture", "Pattern_language",
    ],
    "linguistics": [
        "Sapir–Whorf_hypothesis", "Pragmatics", "Pidgin",
        "Language_acquisition", "Phoneme", "Semantic_change",
        "Code-switching", "Language_death", "Universal_grammar",
        "Computational_linguistics", "Discourse_analysis", "Etymology",
        "Sociolinguistics", "Morphology_(linguistics)", "Syntax",
        "Cognitive_linguistics", "Historical_linguistics", "Creole_language",
        "Psycholinguistics", "Speech_act",
    ],
    "economic_history": [
        "Tulip_mania", "South_Sea_Company", "Hanseatic_League",
        "Silk_Road", "Bretton_Woods_system", "Dutch_East_India_Company",
        "Great_Depression", "Marshall_Plan", "Enclosure",
        "Industrial_Revolution", "Gold_standard", "Mercantilism",
        "Physiocracy", "East_India_Company", "Corn_Laws",
        "Bank_of_England", "Spice_trade", "Panic_of_1907",
        "Hyperinflation_in_the_Weimar_Republic", "Columbian_exchange",
    ],
    "legal_theory": [
        "Natural_law", "Legal_positivism", "Critical_legal_studies",
        "Law_and_economics", "Originalism", "Legal_realism",
        "Rule_of_law", "Social_contract", "Jurisprudence",
        "Hart–Fuller_debate", "Restorative_justice", "Common_law",
        "Customary_law", "Legal_pluralism", "Regulatory_capture",
        "Separation_of_powers", "Habeas_corpus", "Stare_decisis",
        "Adversarial_system", "Due_process",
    ],
    "physics": [
        "Entropy", "Quantum_entanglement", "Phase_transition",
        "Symmetry_breaking", "Emergence", "Renormalization",
        "Statistical_mechanics", "Thermodynamics", "Wave–particle_duality",
        "Uncertainty_principle", "Conservation_law", "Noether's_theorem",
        "Critical_phenomena", "Superposition_principle", "Fermi_paradox",
        "Boltzmann_brain", "Arrow_of_time", "Ergodicity",
        "Dissipative_system", "Self-organized_criticality",
    ],
    "music": [
        "Counterpoint", "Polyrhythm", "Twelve-tone_technique",
        "Harmonic_series_(music)", "Timbre", "Syncopation",
        "Tonality", "Atonality", "Musical_form", "Consonance_and_dissonance",
        "Microtonality", "Aleatoric_music", "Spectral_music",
        "Minimalist_music", "Gamelan", "Raga", "Musique_concrète",
        "Sound_synthesis", "Pythagorean_tuning", "Just_intonation",
    ],
    "global_history": [
        "Axial_Age", "Mongol_Empire", "Atlantic_slave_trade",
        "Reconquista", "Fall_of_Constantinople", "Meiji_Restoration",
        "Scramble_for_Africa", "Opium_Wars", "Printing_press",
        "Agricultural_revolution", "Phoenicia", "Indus_Valley_Civilisation",
        "Library_of_Alexandria", "Treaty_of_Westphalia", "Bandung_Conference",
        "Haitian_Revolution", "Zheng_He", "Trans-Saharan_trade",
        "Age_of_Discovery", "Pax_Mongolica",
    ],
}

DEFAULT_ARXIV_SCHEDULE: dict[int, str] = {
    0: "math",
    1: "q-bio",
    2: "cs.AI",
    3: "econ",
    4: "physics.soc-ph",
    5: "stat.ML",
    6: "cond-mat",
}

TAG_TO_DOMAIN: dict[str, str] = {
    "philosophy": "philosophy",
    "ethics": "philosophy",
    "epistemology": "philosophy",
    "metaphysics": "philosophy",
    "economics": "economics",
    "finance": "economics",
    "markets": "economics",
    "ai": "ai",
    "machine-learning": "ai",
    "artificial-intelligence": "ai",
    "deep-learning": "ai",
    "psychology": "psychology",
    "cognition": "psychology",
    "behavior": "psychology",
    "neuroscience": "neuroscience",
    "brain": "neuroscience",
    "consciousness": "neuroscience",
    "biology": "biology",
    "evolution": "biology",
    "genetics": "biology",
    "mathematics": "mathematics",
    "math": "mathematics",
    "statistics": "mathematics",
    "technology": "technology",
    "software": "technology",
    "engineering": "technology",
    "history": "history",
    "politics": "politics",
    "sociology": "sociology",
    "culture": "sociology",
    "literature": "literature",
    "writing": "literature",
    "art": "art",
    "design": "art",
    "physics": "physics",
    "complexity": "complexity",
    "systems": "complexity",
}

DEFAULT_ADJACENCY_MAP: dict[str, list[str]] = {
    "philosophy": ["cognitive_science", "neuroscience", "anthropology"],
    "economics": ["behavioral_psychology", "game_theory", "ecology"],
    "ai": ["cognitive_science", "philosophy_of_mind", "evolutionary_biology"],
    "psychology": ["neuroscience", "anthropology", "evolutionary_biology"],
    "neuroscience": ["philosophy_of_mind", "computational_biology", "psychology"],
    "biology": ["information_theory", "network_science", "chemistry"],
    "mathematics": ["philosophy", "physics", "computer_science"],
    "technology": ["sociology", "anthropology", "economics"],
    "history": ["anthropology", "economics", "sociology"],
    "politics": ["game_theory", "sociology", "economics"],
    "sociology": ["anthropology", "psychology", "network_science"],
    "literature": ["cognitive_science", "anthropology", "philosophy"],
    "art": ["cognitive_science", "mathematics", "philosophy"],
    "physics": ["mathematics", "philosophy", "information_theory"],
    "complexity": ["ecology", "network_science", "evolutionary_biology"],
}

ADJACENT_DOMAIN_POOLS: dict[str, list[str]] = {
    "cognitive_science": [
        "Embodied_cognition", "Cognitive_load", "Dual_process_theory",
        "Mental_model", "Situated_cognition", "Cognitive_bias",
    ],
    "neuroscience": [
        "Neuroplasticity", "Default_mode_network", "Mirror_neuron",
        "Predictive_coding", "Connectome", "Hebbian_theory",
    ],
    "anthropology": [
        "Structural_anthropology", "Liminality", "Gift_economy",
        "Thick_description", "Cultural_relativism", "Kinship",
    ],
    "behavioral_psychology": [
        "Nudge_theory", "Prospect_theory", "Cognitive_dissonance",
        "Anchoring_(cognitive_bias)", "Availability_heuristic", "Framing_effect_(psychology)",
    ],
    "game_theory": [
        "Nash_equilibrium", "Prisoner's_dilemma", "Mechanism_design",
        "Evolutionarily_stable_strategy", "Auction_theory", "Tragedy_of_the_commons",
    ],
    "ecology": [
        "Ecosystem_engineer", "Trophic_cascade", "Island_biogeography",
        "Ecological_niche", "Succession_(ecology)", "Keystone_species",
    ],
    "philosophy_of_mind": [
        "Chinese_room", "Functionalism_(philosophy_of_mind)", "Qualia",
        "Extended_mind_thesis", "Eliminative_materialism", "Intentionality",
    ],
    "evolutionary_biology": [
        "Symbiogenesis", "Punctuated_equilibrium", "Red_Queen_hypothesis",
        "Exaptation", "Coevolution", "Niche_construction",
    ],
    "computational_biology": [
        "Genetic_algorithm", "Artificial_neural_network", "Systems_biology",
        "Bioinformatics", "Molecular_dynamics", "Protein_folding",
    ],
    "information_theory": [
        "Entropy_(information_theory)", "Shannon's_source_coding_theorem",
        "Kolmogorov_complexity", "Mutual_information", "Channel_capacity",
        "Data_compression",
    ],
    "network_science": [
        "Scale-free_network", "Small-world_network", "Preferential_attachment",
        "Community_structure", "Network_motif", "Centrality",
    ],
    "chemistry": [
        "Autocatalysis", "Self-assembly", "Phase_transition",
        "Chirality_(chemistry)", "Catalysis", "Supramolecular_chemistry",
    ],
    "computer_science": [
        "Halting_problem", "P_versus_NP_problem", "Lambda_calculus",
        "Turing_machine", "Algorithmic_information_theory", "Distributed_computing",
    ],
}


# ── Fetchers ────────────────────────────────────────────────────


def _fetch_wikipedia_summary(title: str) -> dict | None:
    """Fetch summary from Wikipedia REST API. Returns {title, summary, url} or None."""
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
    req = Request(url, headers={"User-Agent": "IdeaEngine/1.0 (educational research tool)"})
    try:
        import json

        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            extract = data.get("extract", "")
            # Truncate to ~4 sentences
            sentences = extract.split(". ")
            summary = ". ".join(sentences[:4])
            if not summary.endswith("."):
                summary += "."
            return {
                "title": data.get("title", title),
                "summary": summary,
                "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
            }
    except (URLError, TimeoutError, Exception) as e:
        logger.warning(f"Wikipedia fetch failed for '{title}': {e}")
        return None


def _fetch_arxiv_paper(category: str, max_results: int = 5) -> dict | None:
    """Fetch a random recent paper from arXiv. Returns {title, summary, url} or None."""
    url = (
        f"http://export.arxiv.org/api/query?"
        f"search_query=cat:{category}&sortBy=submittedDate&max_results={max_results}"
    )
    req = Request(url, headers={"User-Agent": "IdeaEngine/1.0 (educational research tool)"})
    try:
        with urlopen(req, timeout=15) as resp:
            xml_data = resp.read().decode("utf-8")

        root = ET.fromstring(xml_data)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)

        if not entries:
            logger.warning(f"No arXiv entries found for category '{category}'")
            return None

        entry = random.choice(entries)
        title = entry.findtext("atom:title", "", ns).strip().replace("\n", " ")
        summary = entry.findtext("atom:summary", "", ns).strip().replace("\n", " ")

        # Truncate summary
        sentences = summary.split(". ")
        summary = ". ".join(sentences[:4])
        if not summary.endswith("."):
            summary += "."

        # Get link
        link = ""
        for link_el in entry.findall("atom:link", ns):
            if link_el.get("type") == "text/html":
                link = link_el.get("href", "")
                break
        if not link:
            id_text = entry.findtext("atom:id", "", ns)
            link = id_text

        return {"title": title, "summary": summary, "url": link}
    except (URLError, TimeoutError, ET.ParseError, Exception) as e:
        logger.warning(f"arXiv fetch failed for category '{category}': {e}")
        return None


# ── Strategies ──────────────────────────────────────────────────


def _strategy_curated_random(config: dict) -> EntropyConcept | None:
    """Strategy A: Pick from curated domain pools."""
    entropy_config = config.get("entropy", {})
    curated_config = entropy_config.get("curated_random", {})
    domains = curated_config.get("domains", list(CURATED_DOMAIN_POOLS.keys()))

    # Filter to domains we actually have pools for
    available = [d for d in domains if d in CURATED_DOMAIN_POOLS]
    if not available:
        logger.warning("No valid curated domains configured")
        return None

    domain = random.choice(available)
    article = random.choice(CURATED_DOMAIN_POOLS[domain])

    result = _fetch_wikipedia_summary(article)
    if not result:
        return None

    return EntropyConcept(
        title=result["title"],
        summary=result["summary"],
        source="wikipedia",
        domain=domain,
        strategy="curated_random",
        url=result.get("url", ""),
    )


def _strategy_arxiv_rotation(config: dict, run_count: int = 0) -> EntropyConcept | None:
    """Strategy B: Cycle through arXiv fields by day of week."""
    entropy_config = config.get("entropy", {})
    arxiv_config = entropy_config.get("arxiv_rotation", {})
    schedule = arxiv_config.get("schedule", DEFAULT_ARXIV_SCHEDULE)
    max_results = arxiv_config.get("max_results", 5)

    # Convert string keys to int if loaded from YAML
    schedule = {int(k): v for k, v in schedule.items()}

    weekday = datetime.now().weekday()
    category = schedule.get(weekday, "math")

    result = _fetch_arxiv_paper(category, max_results)
    if not result:
        return None

    return EntropyConcept(
        title=result["title"],
        summary=result["summary"],
        source="arxiv",
        domain=category,
        strategy="arxiv_rotation",
        url=result.get("url", ""),
    )


def _detect_vault_density(vault_notes: list) -> str | None:
    """Count tags across vault notes, map to domains, return densest domain."""
    domain_counts: dict[str, int] = {}

    for note in vault_notes:
        for tag in getattr(note, "tags", []):
            tag_lower = tag.lower().strip("#").strip()
            domain = TAG_TO_DOMAIN.get(tag_lower)
            if domain:
                domain_counts[domain] = domain_counts.get(domain, 0) + 1

    if not domain_counts:
        return None

    return max(domain_counts, key=domain_counts.get)


def _strategy_adjacent_possible(
    config: dict, vault_notes: list | None = None
) -> EntropyConcept | None:
    """Strategy C: Detect vault density, inject from adjacent domain."""
    entropy_config = config.get("entropy", {})
    adj_config = entropy_config.get("adjacent_possible", {})
    fallback_domain = adj_config.get("fallback_domain", "mathematics")

    densest = None
    if vault_notes:
        densest = _detect_vault_density(vault_notes)

    if not densest:
        densest = fallback_domain

    # Find adjacent domains
    adjacents = DEFAULT_ADJACENCY_MAP.get(densest, [])
    if not adjacents:
        adjacents = DEFAULT_ADJACENCY_MAP.get(fallback_domain, ["cognitive_science"])

    # Filter to domains we have pools for
    available = [d for d in adjacents if d in ADJACENT_DOMAIN_POOLS]
    if not available:
        logger.warning(f"No adjacent domain pools available for '{densest}'")
        return None

    adj_domain = random.choice(available)
    article = random.choice(ADJACENT_DOMAIN_POOLS[adj_domain])

    result = _fetch_wikipedia_summary(article)
    if not result:
        return None

    return EntropyConcept(
        title=result["title"],
        summary=result["summary"],
        source="wikipedia",
        domain=adj_domain,
        strategy="adjacent_possible",
        url=result.get("url", ""),
    )


# ── Public API ──────────────────────────────────────────────────


def fetch_entropy_concept(
    config: dict,
    vault_notes: list | None = None,
    run_count: int = 0,
) -> EntropyConcept | None:
    """Fetch an external concept using the configured strategy.

    Returns None on any failure (logged warning, run continues).
    """
    entropy_config = config.get("entropy", {})

    if not entropy_config.get("enabled", True):
        return None

    strategy = entropy_config.get("strategy", "curated_random")

    try:
        if strategy == "curated_random":
            return _strategy_curated_random(config)
        elif strategy == "arxiv_rotation":
            return _strategy_arxiv_rotation(config, run_count)
        elif strategy == "adjacent_possible":
            return _strategy_adjacent_possible(config, vault_notes)
        else:
            logger.warning(f"Unknown entropy strategy: {strategy}")
            return None
    except Exception as e:
        logger.warning(f"Entropy injection failed ({strategy}): {e}")
        return None
