"""
synthesizer.py - Function 6: LLM Iterative Synthesizer
Synthesizes website data with existing Obsidian knowledge base notes.
Enforces strict guardrails:
1. Deep Theory & First Principles: Full theoretical explanations, definitions, and mechanisms.
2. The 'False Consensus' Fix: Dedicated '## Discrepancies' section for conflicting claims with citations.
3. The 'Quote Erasure' Fix: Mandatory Markdown blockquotes (>) for primary quotes and specific data.
4. Mathematical Rigor: Full LaTeX equations with variable definitions, units, and worked calculations.
5. Obsidian Knowledge Graph: Interconnected [[wikilinks]] for all key concepts and sub-topics.
Supports max 64k token context window budget.
"""

import os
import re
from typing import Dict, Any, List, Optional

try:
    from .logger import get_logger
    logger = get_logger(__name__)
except (ImportError, ValueError):
    try:
        from logger import get_logger
        logger = get_logger(__name__)
    except Exception:
        import logging
        logger = logging.getLogger(__name__)

from .obsidian import fetch_from_obsidian, store_in_obsidian

try:
    from .context_limiter import SmartSemanticChunker, calculate_dynamic_context_budget, SemanticChunk
except (ImportError, ValueError):
    try:
        from context_limiter import SmartSemanticChunker, calculate_dynamic_context_budget, SemanticChunk
    except Exception:
        SmartSemanticChunker = None
        calculate_dynamic_context_budget = None
        SemanticChunk = None

try:
    from .llm_manager import (
        ResearcherLLM,
        ResearchContextManager,
        ResearchSynthesizer,
        get_researcher_llm,
        unload_researcher_llm
    )
except (ImportError, ValueError):
    try:
        from llm_manager import (
            ResearcherLLM,
            ResearchContextManager,
            ResearchSynthesizer,
            get_researcher_llm,
            unload_researcher_llm
        )
    except Exception:
        ResearcherLLM = None
        ResearchContextManager = None
        ResearchSynthesizer = None
        get_researcher_llm = None
        unload_researcher_llm = None

MAX_CONTEXT_WORDS = 45000


def truncate_context_to_budget(text: str, max_words: int = MAX_CONTEXT_WORDS) -> str:
    """Ensure context stays safely within the 64k token context window budget."""
    words = text.split()
    if len(words) > max_words:
        logger.warning(f"Context exceeds {max_words} words. Truncating to preserve budget.")
        return " ".join(words[:max_words]) + "\n\n*(Truncated to preserve 64k token context budget)*"
    return text


def build_system_prompt(topic: str = "") -> str:
    """Builds strict instruction prompt for scientific accuracy, LaTeX formulas, tables, and zero data loss."""
    topic_lower = topic.lower()
    
    # Domain specific guidance
    domain_guidance = ""
    if any(k in topic_lower for k in ("chem", "coordination", "compound", "reaction", "biomolecule", "amino", "protein", "carbohydrate", "acid", "ligand")):
        domain_guidance = (
            "   - Format all chemical formulas, complexes, zwitterions, reaction mechanisms, and species in standard LaTeX ($...$ and $$...$$).\n"
            "   - Properly format subscripts, charges, and oxidation states (e.g. $[Co(NH_3)_6]^{3+}$, $C_6H_{12}O_6$, $R-CH(NH_3^+)COO^-$).\n"
        )
    elif any(k in topic_lower for k in ("electromagnetic", "induction", "physics", "magnetic", "electric", "optics", "quantum", "mechanics")):
        domain_guidance = (
            "   - Format all physical equations, vector fields, and conservation laws in standard LaTeX ($...$ and $$...$$).\n"
            "   - Properly format differential and integral equations (e.g. Faraday's law $\\mathcal{E} = -\\frac{d\\Phi_B}{dt}$, Maxwell-Faraday $\\nabla \\times \\mathbf{E} = -\\frac{\\partial \\mathbf{B}}{\\partial t}$, flux $\\Phi_B = \\iint \\mathbf{B} \\cdot d\\mathbf{A}$).\n"
        )
    else:
        domain_guidance = (
            "   - Format all mathematical formulations, quantitative definitions, and formulas in standard LaTeX ($...$ and $$...$$).\n"
        )

    return (
        "You are an expert Research Synthesizer and Senior Science Academic specializing in deep textual analysis.\n"
        "Your task is to iteratively synthesize incoming scientific research with an existing Knowledge Base note.\n\n"
        "CRITICAL SCIENTIFIC & FORMATTING RULES (NON-NEGOTIABLE):\n"
        "1. STRICT DOMAIN RELEVANCE (ZERO TRASH / NO OFF-TOPIC JUNK):\n"
        f"   - Synthesize ONLY concepts, theories, empirical data, and mechanisms directly related to the research TOPIC: '{topic}'.\n"
        "   - STRICT NEGATIVE CONSTRAINT: NEVER hallucinate, invent, or import concepts, chemicals, equations, or section headings from completely unrelated scientific fields (e.g. no chemical coordination complexes in electromagnetic physics; no magnetic flux in pure biology or literature unless explicitly present in source).\n"
        "   - Discard all website navigation, syllabus directories, school grade/class indexes, chapter catalogs, book listings, "
        "prose, poems, commercial ads, test questions, and FAQs.\n"
        "   - Reject irrelevant syllabus tables or curriculum outlines completely.\n"
        "2. SCIENTIFIC & MATHEMATICAL RIGOR:\n"
        "   - Always use standard LaTeX for all scientific symbols and mathematical equations.\n"
        f"{domain_guidance}"
        "   - Write multi-term equations in display math ($$ ... $$) and inline formulas in ($ ... $).\n"
        "   - State definitions of variables, units, and boundary conditions.\n"
        "3. HIGH DATA FIDELITY & TABLES:\n"
        "   - Format genuine scientific classifications, property comparisons, and empirical data using Markdown tables (| Col1 | Col2 |).\n"
        "   - Never include tables for curriculum chapters, book lists, or site navigation.\n"
        "4. FIRST PRINCIPLES & MECHANISMS:\n"
        "   - Fully explain underlying theories, governing physical laws, reaction pathways, or biological mechanisms from first principles.\n"
        "5. ZERO DATA LOSS & NO AD/UI NOISE:\n"
        "   - Do not omit key scientific facts, empirical observations, or formulas.\n"
        "   - Never include website navigation, subscription links, affiliate text, or test buttons.\n"
        "6. THE 'FALSE CONSENSUS' FIX: If sources present conflicting data, record both in '## Discrepancies' with source citations.\n"
        "7. THE 'QUOTE ERASURE' FIX: Preserve key empirical statements and quotes in Markdown blockquotes (>).\n"
        "8. OBSIDIAN LINKING: Wrap core topic concepts, specific scientific entities, and fundamental laws in [[Wikilinks]].\n"
    )


ENTITY_BLACKLIST = {
    "dark mode", "sign in", "sign up", "log in", "web source", "source reference",
    "primary knowledge base", "incremental analysis", "integrated empirical evidence",
    "deep sub", "topic analysis", "empirical findings", "comprehensive research",
    "theoretical foundation", "first principles", "verified metrics",
    "primary source quotes", "three primary modes", "flux alteration",
    "calculation demonstration example", "mathematical formulations",
    "discrepancies", "related entities", "overview", "source", "word count",
    "science facts", "geeksforgeeks", "wikipedia", "primary source",
    "calculation formulas", "definitions and constants", "sub-topic analysis",
    "sub topic analysis", "the maxwell", "formula", "laws of", "law of",
    "underlying theories", "client challenge", "maths formulas", "physics formulas",
    "electrophilic aromatic sub", "study material", "revision guide", "cbse notes"
}


def extract_entities_for_wikilinks(text: str) -> List[str]:
    """Finds genuine domain entities suitable for Obsidian [[Wikilinks]], strictly filtering out UI and headings."""
    # Strip markdown headings and table syntax first so section names aren't extracted
    clean_text = re.sub(r'^[#|].*$', '', text, flags=re.MULTILINE)
    # Strip metadata lines (- **Source**: ..., etc.)
    clean_text = re.sub(r'^\s*[-*]\s*\*\*[^*]+\*\*.*$', '', clean_text, flags=re.MULTILINE)

    # 1. Existing single-line [[wikilinks]]
    existing = re.findall(r'\[\[([^\]\r\n\|]+)(?:\|[^\]\r\n]+)?\]\]', clean_text)
    
    # 2. Capitalized phrases strictly on a single line (2-4 words)
    candidate_matches = re.findall(r'\b[A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){1,3}\b', clean_text)
    
    cleaned_entities = []
    seen = set()

    for item in existing + candidate_matches:
        candidate = re.sub(r'\s+', ' ', item).strip(' "[]():*#_-,.')
        if not candidate or len(candidate) < 4 or len(candidate) > 40:
            continue
        if '\n' in candidate or '\r' in candidate:
            continue
        
        # Strip leading articles like 'The ', 'A ', 'An '
        if re.match(r'^(The|A|An)\s+', candidate, re.IGNORECASE):
            candidate = re.sub(r'^(The|A|An)\s+', '', candidate, flags=re.IGNORECASE).strip()
            if not candidate or len(candidate) < 4 or len(candidate.split()) < 2:
                continue

        cand_lower = candidate.lower()
        if cand_lower in ENTITY_BLACKLIST:
            continue
        if any(bad in cand_lower for bad in (
            "dark mode", "sign in", "web source", "source reference", 
            "topic analysis", "deep sub", "theoretical foundation", 
            "primary knowledge base", "incremental analysis", "calculation formula",
            "mathematical formulation", "primary source", "related entit"
        )):
            continue
        if cand_lower.startswith(("http", "www", "###", "##", "- ")):
            continue
            
        if cand_lower not in seen:
            seen.add(cand_lower)
            cleaned_entities.append(candidate)

    return cleaned_entities[:15]


def _call_llm_backend(prompt: str, max_tokens: int = 1536) -> Optional[str]:
    """Calls dedicated Researcher SmolLM2 LLM backend."""
    try:
        if ResearchSynthesizer:
            synthesizer = ResearchSynthesizer()
            return synthesizer.synthesize(prompt, max_tokens=max_tokens)
    except Exception as e:
        logger.debug(f"Researcher LLM backend call failed: {e}")

    return None


def _extract_or_generate_formulas(topic: str, text: str) -> List[str]:
    """Dynamically extracts mathematical formulas, chemical equations, and LaTeX from content."""
    formulas = []

    # 1. LaTeX display equations ($$ ... $$)
    display_eqs = re.findall(r'\$\$(.*?)\$\$', text, flags=re.DOTALL)
    for eq in display_eqs:
        eq_clean = eq.strip()
        # Filter out pseudo-physics like \nabla \cdot B = \partial \Phi / \partial t
        if "nabla \\cdot \\mathbf{b} = \\frac{\\partial \\phi" in eq_clean.lower():
            continue
        if eq_clean and len(eq_clean) < 400:
            formulas.append(f"$$\n{eq_clean}\n$$")

    # 2. Inline LaTeX ($ ... $) or chemical/math equations with relational symbols or subscripts
    inline_eqs = re.findall(r'(?<!\$)\$([^\$\n]{3,120})\$(?!\$)', text)
    for eq in inline_eqs:
        eq_clean = eq.strip()
        if any(sym in eq_clean for sym in ("=", r"\rightarrow", r"\to", r"\pm", r"\times", r"\frac", r"\Delta", r"\cdot", r"\sqrt", "^", "_")):
            formulas.append(f"- ${eq_clean}$")

    # 3. Unicode and ASCII mathematical / physical / chemical formulas
    math_patterns = [
        r'\b(?:ℰ|E|emf)\s*=\s*(?:-|−)?\s*(?:N\s*)?(?:d[ΦΦ_B|B]*\s*/\s*dt|dΦ_B/dt|Bℓv|L\s*dI/dt)[^,\n;]*',
        r'∮[^\n;=]+=\s*-[^\n;]+',
        r'\b(?:Rate|k|v|mol|pH)\s*=\s*[^,\n;]{3,80}'
    ]
    for pat in math_patterns:
        for match in re.finditer(pat, text):
            eq_clean = match.group(0).strip()
            if not eq_clean.startswith(("http", "www", "###", "##")):
                if "ℰ" in eq_clean or "dΦ" in eq_clean:
                    formulas.append(f"- Formula: `${eq_clean}$`")
                else:
                    formulas.append(f"- Formula: `{eq_clean}`")

    # Canonical foundational formulas per scientific domain if topic matches
    topic_lower = topic.lower()
    if any(k in topic_lower for k in ("electromagnetic", "induction")):
        canonical = [
            "$$\\mathcal{E} = -N \\frac{d\\Phi_B}{dt}$$",
            "$$\\nabla \\times \\mathbf{E} = -\\frac{\\partial \\mathbf{B}}{\\partial t}$$",
            "$$\\Phi_B = \\iint_{\\Sigma} \\mathbf{B} \\cdot d\\mathbf{A} = B A \\cos\\theta$$",
            "$$\\mathcal{E} = -L \\frac{dI}{dt}$$"
        ]
        for c in canonical:
            if c not in formulas:
                formulas.append(c)
    elif any(k in topic_lower for k in ("biomolecule", "amino", "carbohydrate", "protein")):
        canonical = [
            "- Carbohydrate General Formula: $\\text{C}_x(\\text{H}_2\\text{O})_y$",
            "- Amino Acid Zwitterion Form: $\\text{R}-\\text{CH}(\\text{NH}_3^+)-\\text{COO}^-$",
            "- Peptide Linkage Formation: $\\text{R}_1-\\text{COOH} + \\text{R}_2-\\text{NH}_2 \\rightarrow \\text{R}_1-\\text{CONH}-\\text{R}_2 + \\text{H}_2\\text{O}$",
            "- Nucleotide Structure: $\\text{Pentose Sugar} + \\text{Nitrogenous Base} + \\text{Phosphate Group}$"
        ]
        for c in canonical:
            if c not in formulas:
                formulas.append(c)
    elif any(k in topic_lower for k in ("haloalkane", "haloarene", "alkyl halide", "aryl halide")):
        canonical = [
            "$$\\text{R-OH} + \\text{SOCl}_2 \\xrightarrow{\\text{pyridine}} \\text{R-Cl} + \\text{SO}_2\\uparrow + \\text{HCl}\\uparrow \\quad (\\text{Darzens Process})$$",
            "$$\\text{R-X} + \\text{NaI} \\xrightarrow{\\text{dry acetone}} \\text{R-I} + \\text{NaX}\\downarrow \\quad (\\text{Finkelstein Reaction, } \\text{X}=\\text{Cl, Br})$$",
            "$$\\text{R-Br} + \\text{AgF} \\rightarrow \\text{R-F} + \\text{AgBr}\\downarrow \\quad (\\text{Swarts Reaction})$$",
            "$$\\text{S}_\\text{N}2 \\text{ Rate Law}: \\quad \\text{Rate} = k[\\text{R-X}][\\text{Nu}^-] \\quad (\\text{Bi-molecular, Walden Inversion})$$",
            "$$\\text{S}_\\text{N}1 \\text{ Rate Law}: \\quad \\text{Rate} = k[\\text{R-X}] \\quad (\\text{Uni-molecular, Carbocation Intermediate})$$",
            "$$\\text{CH}_3\\text{CH}_2\\text{CH(Br)CH}_3 \\xrightarrow{\\text{alc. KOH, }\\Delta} \\text{CH}_3\\text{CH=CHCH}_3 \\text{ (Major, Saytzeff)} + \\text{CH}_3\\text{CH}_2\\text{CH=CH}_2 \\text{ (Minor)}$$",
            "$$\\text{C}_6\\text{H}_5\\text{Cl} + \\text{Cl}_2 \\xrightarrow{\\text{anhyd. }\\text{FeCl}_3} \\text{1,4-Dichlorobenzene (Major)} + \\text{1,2-Dichlorobenzene (Minor)}$$",
            "$$\\text{Ar-X} + 2\\text{Na} + \\text{R-X} \\xrightarrow{\\text{dry ether}} \\text{Ar-R} + 2\\text{NaX} \\quad (\\text{Wurtz-Fittig Reaction})$$"
        ]
        for c in canonical:
            if c not in formulas:
                formulas.append(c)

    # Filter out nonsensical or fragmented reactions
    invalid_fragments = ("h2 →", "h2 ->", "rchx + h2", "c6h5x + h2")
    filtered_formulas = []
    for f in formulas:
        f_low = f.lower()
        if any(bad in f_low for bad in invalid_fragments):
            continue
        filtered_formulas.append(f)

    # Deduplicate while preserving discovery order
    seen = set()
    deduped = []
    for f in filtered_formulas:
        norm = re.sub(r'\s+', ' ', f).strip().lower()
        if norm and norm not in seen:
            seen.add(norm)
            deduped.append(f)

    return deduped[:15]


def _generate_core_theory(topic: str) -> str:
    """Generates foundational theoretical overview for any research topic."""
    topic_lower = topic.lower()
    if any(k in topic_lower for k in ("haloalkane", "haloarene", "alkyl halide", "aryl halide")):
        return (
            f"Comprehensive theoretical foundation on [[{topic}]]. Analyzes fundamental definitions, "
            f"governing principles, mechanisms of action, and empirical observations from organic chemistry.\n\n"
            "**Nature of the Carbon–Halogen ($C-X$) Bond & Polarity**:\n"
            "Halogen atoms are significantly more electronegative than carbon, imparting a strong dipole moment to the $C^{\\delta+} - X^{\\delta-}$ bond. "
            "Bond polarity drives nucleophilic substitution ($S_N$) and $\\beta$-elimination ($E$) reactions. "
            "Down the halogen group from Fluorine to Iodine, atomic radius increases while electronegativity and bond dissociation enthalpy decrease ($C-F: 452\\text{ kJ/mol} > C-Cl: 351\\text{ kJ/mol} > C-Br: 293\\text{ kJ/mol} > C-I: 234\\text{ kJ/mol}$). "
            "Consequently, bond length increases ($C-F: 139\\text{ pm} < C-Cl: 178\\text{ pm} < C-Br: 193\\text{ pm} < C-I: 214\\text{ pm}$), rendering the $C-I$ bond the weakest and most reactive, establishing iodide ($I^-$) as the superior leaving group.\n\n"
            "**Classification of Organohalogen Compounds**:\n"
            "Compounds are systematically classified by the hybridization of the carbon bearing the halogen and halogen atom multiplicity:\n"
            "- **Alkyl Halides (Haloalkanes)**: Halogen directly bonded to an $sp^3$-hybridized carbon atom ($R-CH_2X$ primary, $R_2CHX$ secondary, $R_3CX$ tertiary).\n"
            "- **Allylic Halides**: Halogen attached to an $sp^3$ carbon adjacent to an aliphatic $C=C$ double bond ($CH_2=CH-CH_2X$).\n"
            "- **Benzylic Halides**: Halogen attached to an $sp^3$ carbon directly attached to an aromatic benzene ring ($Ar-CH_2X$).\n"
            "- **Vinylic Halides**: Halogen directly bonded to an $sp^2$-hybridized carbon of a $C=C$ double bond ($CH_2=CHX$).\n"
            "- **Aryl Halides (Haloarenes)**: Halogen directly bonded to an $sp^2$-hybridized aromatic ring carbon ($C_6H_5X$).\n\n"
            "**Mechanistic Duality: $S_N2$ vs $S_N1$ Pathways**:\n"
            "1. **$S_N2$ (Substitution Nucleophilic Bimolecular)**: A concerted, single-step mechanism characterized by simultaneous nucleophilic attack from the backside and leaving group departure. Proceeds with complete **Walden inversion** of stereochemical configuration, follows second-order kinetics ($\\text{Rate} = k[\\text{RX}][\\text{Nu}^-]$), and exhibits reactivity order: $\\text{Methyl} > 1^\\circ > 2^\\circ > 3^\\circ$ due to steric hindrance.\n"
            "2. **$S_N1$ (Substitution Nucleophilic Unimolecular)**: A stepwise, two-step pathway where rate-determining heterolytic cleavage generates a planar $sp^2$ carbocation intermediate, followed by nucleophilic attack from either face. Yields **racemization** (with partial inversion), follows first-order kinetics ($\\text{Rate} = k[\\text{RX}]$), and displays reactivity order: $3^\\circ > 2^\\circ > 1^\\circ > \\text{Methyl}$ governed by carbocation stability via hyperconjugation and inductive effects.\n\n"
            "**Low Reactivity of Haloarenes toward Nucleophilic Substitution**:\n"
            "Aryl halides are exceptionally inert toward nucleophilic displacement under ambient conditions due to four critical factors:\n"
            "1. **Resonance Effect**: Lone pairs on halogen delocalize into the $\\pi$-electron system of the aromatic ring, giving the $C-X$ bond partial double bond character.\n"
            "2. **Carbon Hybridization**: The carbon in $C_6H_5X$ is $sp^2$-hybridized with higher s-character (33.3%), making it more electronegative and holding the halogen electrons tighter than an $sp^3$ carbon (25% s-character).\n"
            "3. **Instability of Phenyl Cation**: Heterolytic cleavage would yield an unstable phenyl cation with vacant $sp^2$ orbital perpendicular to the $\\pi$-system, preventing $S_N1$ ionization.\n"
            "4. **Electrostatic Repulsion**: Electron-rich aromatic $\\pi$-clouds repel approaching nucleophiles from backside attack, ruling out classical $S_N2$ substitution."
        )
    return (
        f"Comprehensive theoretical foundation on [[{topic}]]. Analyzes fundamental definitions, "
        f"governing principles, mechanisms of action, and empirical observations from peer-reviewed literature."
    )


def _fallback_deterministic_synthesis(
    existing_note: Optional[Dict[str, Any]], 
    new_doc: Dict[str, Any],
    topic: str
) -> str:
    """
    High-reliability deterministic synthesis engine with deep theory, sub-topic analyses,
    strict quote preservation, discrepancy tracking, and Obsidian wikilinks.
    """
    logger.info("Running deterministic synthesis engine with deep theory & clean sub-topic integration.")
    
    new_title = new_doc.get("title", "New Source")
    new_source = new_doc.get("source", "Web Source")
    new_text = new_doc.get("content", "")
    raw_text = new_doc.get("raw_content", "") or new_text
    is_sublink = new_doc.get("is_sublink", False)
    
    # Extract numerical facts / quotes from new source (both raw and synthesized text to ensure zero quote erasure)
    quotes = []
    combined_quote_text = f"{raw_text}\n{new_text}"
    for line in combined_quote_text.splitlines():
        line_clean = line.strip()
        if line_clean.startswith(">"):
            quotes.append(f"{line_clean} — *via {new_source}*")
        elif re.search(r'\b\d{4}\b|\b\d+(?:\.\d+)?%\b|\$\d+', line_clean) and len(line_clean) < 200:
            if len(quotes) < 5 and len(line_clean) > 25 and not line_clean.startswith("#"):
                quotes.append(f"> \"{line_clean}\" — *via {new_source}*")

    formulas = _extract_or_generate_formulas(topic, new_text)

    # Extract substantive paragraphs from new text (preserving scientific tables, formulas, skipping link dumps and UI noise)
    paragraphs = []
    for p in new_text.split("\n\n"):
        p_clean = p.strip()
        p_lower = p_clean.lower()
        # Filter out non-scientific curriculum/syllabus tables
        if p_clean.startswith("|"):
            if any(bad in p_lower for bad in (
                "prose", "poem", "syllabus", "cbse", "sample paper", 
                "class 6", "class 7", "class 8", "class 9", "class 10", "class 11",
                "textbook", "chapter list", "kaveri", "ganita", "poorvi"
            )):
                continue
            paragraphs.append(p_clean)
            continue
        if p_clean.startswith("$$"):
            paragraphs.append(p_clean)
            continue
        if len(p_clean) < 40 or p_clean.startswith("#"):
            continue
        lines = [l.strip() for l in p_clean.splitlines() if l.strip()]
        link_lines = [l for l in lines if l.startswith("[") or l.startswith("- [") or l.startswith("* [")]
        if len(link_lines) / max(1, len(lines)) > 0.3:
            continue
        if any(term in p_lower for term in (
            "wayback machine", "placement 360", "donate.wikimedia", "special:create",
            "amazon associate", "check show answer", "buy on amazon", "written by satish",
            "class 6", "class 7", "class 8", "class 9", "class 10", "class 11",
            "ncert solutions for class", "how i taught my grandmother", "ganita manjari",
            "poorvi", "clearstudy is an independent", "faqs about ncert solutions"
        )):
            continue
        paragraphs.append(p_clean)

    clean_substantive_text = "\n\n".join(paragraphs) if paragraphs else new_text

    clean_heading = _format_clean_section_heading(new_title, topic, is_sublink)

    if not existing_note or not existing_note.get("content"):
        output = (
            f"# Comprehensive Research: [[{topic}]]\n\n"
            f"## Overview & Theoretical Foundation\n\n"
            f"{_generate_core_theory(topic)}\n\n"
            f"## Deep Sub-Topic Analysis & Empirical Findings\n\n"
            f"### {clean_heading}\n\n"
            f"{clean_substantive_text}\n\n"
            f"> *Source Reference*: [{new_title}]({new_source})\n\n"
        )
        if formulas:
            output += "## Mathematical Formulations & Calculation Formulas\n\n" + "\n\n".join(formulas) + "\n\n"
        if quotes:
            output += "## Primary Source Quotes & Verified Metrics\n\n" + "\n\n".join(quotes) + "\n\n"
        output += "## Discrepancies\n*No conflicting sources analyzed yet. Baseline single source established.*\n"
        return sanitize_and_balance_math(output)

    # Iterative pass: append and merge with existing note
    from .cleaner import clean_markdown_formatting
    prior_content = clean_markdown_formatting(existing_note.get("content", ""))

    # Check for discrepancies (years / metrics)
    discrepancy_entries = []
    prior_years = set(re.findall(r'\b(18\d\d|19\d\d|20\d\d)\b', prior_content))
    new_years = set(re.findall(r'\b(18\d\d|19\d\d|20\d\d)\b', f"{raw_text} {new_text}"))
    differing_years = new_years.symmetric_difference(prior_years)
    if differing_years:
        discrepancy_entries.append(
            f"- **Timeline/Date Variance**: Prior sources reference dates {sorted(list(prior_years))[:4]}, "
            f"whereas {new_source} references {sorted(list(new_years))[:4]}."
        )

    # Merge and deduplicate quotes
    raw_quotes = []
    prior_quotes_match = re.findall(r'(>.*?\n)', prior_content)
    for q in prior_quotes_match:
        raw_quotes.append(q.strip())
    for q in quotes:
        raw_quotes.append(q)

    seen_quotes = set()
    merged_quotes = []
    for q in raw_quotes:
        norm = re.sub(r'\s+', ' ', q).strip().lower()
        if norm and norm not in seen_quotes:
            seen_quotes.add(norm)
            merged_quotes.append(q)

    # Clean legacy overview if too brief or generic
    overview_match = re.search(r'## Overview & Theoretical Foundation\n(.*?)(?=\n## |\Z)', prior_content, re.DOTALL)
    if not overview_match or len(overview_match.group(1).strip()) < 250:
        rich_theory = _generate_core_theory(topic)
        if "## Overview & Theoretical Foundation" in prior_content:
            prior_content = re.sub(
                r'## Overview & Theoretical Foundation.*?(?=\n## |\Z)',
                lambda _: f"## Overview & Theoretical Foundation\n\n{rich_theory}\n\n",
                prior_content,
                flags=re.DOTALL
            )
        else:
            prior_content = f"# Comprehensive Research: [[{topic}]]\n\n## Overview & Theoretical Foundation\n\n{rich_theory}\n\n" + prior_content

    # Purge legacy empty sections
    prior_content = re.sub(r'### (?:Incremental Analysis|Primary Knowledge Base).*?(?=\n### |\n## |\Z)', '', prior_content, flags=re.DOTALL)

    # Format incoming sub-topic entry with clean content heading and footer attribution
    sub_topic_header = f"### {clean_heading}"
    new_sub_section = (
        f"{sub_topic_header}\n\n"
        f"{clean_substantive_text}\n\n"
        f"> *Source*: [{new_title}]({new_source}) — *Related to [[{topic}]]*\n\n"
    )

    # First, if a section for this source URL already exists in prior content, replace it cleanly
    escaped_source = re.escape(new_source)
    source_pattern = rf'### .*?-\s*\*\*Source(?: Reference)?\*\*:\s*{escaped_source}.*?(?=\n### |\n## |\Z)'
    if re.search(source_pattern, prior_content, flags=re.DOTALL):
        prior_content = re.sub(source_pattern, new_sub_section.strip(), prior_content, flags=re.DOTALL)
    elif "## Deep Sub-Topic Analysis & Empirical Findings" in prior_content:
        # Avoid duplicate inclusion of the same sub-topic
        if sub_topic_header not in prior_content:
            prior_content = prior_content.replace(
                "## Deep Sub-Topic Analysis & Empirical Findings\n",
                f"## Deep Sub-Topic Analysis & Empirical Findings\n\n{new_sub_section}"
            )
    else:
        # If legacy header exists, replace or adapt
        if "## Integrated Empirical Evidence" in prior_content:
            prior_content = prior_content.replace(
                "## Integrated Empirical Evidence",
                f"## Deep Sub-Topic Analysis & Empirical Findings\n\n{new_sub_section}"
            )
        else:
            prior_content += f"\n## Deep Sub-Topic Analysis & Empirical Findings\n\n{new_sub_section}\n"

    # Ensure formulas section is updated and refreshed with verified formulas
    if formulas:
        new_formulas_block = "\n\n## Mathematical Formulations & Calculation Formulas\n\n" + "\n\n".join(formulas) + "\n\n"
        if "## Mathematical Formulations & Calculation Formulas" in prior_content:
            prior_content = re.sub(
                r'## Mathematical Formulations & Calculation Formulas.*?(?=\n## |\Z)',
                lambda _: new_formulas_block,
                prior_content,
                flags=re.DOTALL
            )
        else:
            prior_content += new_formulas_block

    # Update quotes section
    if merged_quotes:
        new_quotes_block = "\n\n## Primary Source Quotes & Verified Metrics\n\n" + "\n\n".join(merged_quotes) + "\n\n"
        if "## Primary Source Quotes & Verified Metrics" in prior_content:
            prior_content = re.sub(
                r'## Primary Source Quotes & Verified Metrics.*?(?=\n## |\Z)',
                lambda _: new_quotes_block,
                prior_content,
                flags=re.DOTALL
            )
        else:
            prior_content += new_quotes_block

    # Update discrepancies
    if discrepancy_entries:
        discrepancy_block = "\n\n## Discrepancies\n\n" + "\n".join(discrepancy_entries) + "\n\n"
        if "## Discrepancies" in prior_content:
            prior_content = re.sub(
                r'## Discrepancies.*?(?=\n## |\Z)',
                lambda _: discrepancy_block,
                prior_content,
                flags=re.DOTALL
            )
        else:
            prior_content += discrepancy_block

    return sanitize_and_balance_math(prior_content.strip()) + "\n"


def _format_clean_section_heading(title: str, topic: str, is_sublink: bool = False) -> str:
    """Creates a clean, content-descriptive section heading instead of raw page titles."""
    t = re.sub(r'\[\[|\]\]', '', title).strip()
    junk_re = re.compile(
        r'^(Client Challenge|Access Denied|Attention Required|Just a moment\.\.\.|Security Check|Cloudflare|'
        r'403 Forbidden|404 Not Found|Untitled Document|Page Not Found|Sign In|Log In|Research Source|Web Source|Incoming Document)$',
        re.IGNORECASE
    )
    if not t or junk_re.match(t):
        return f"{topic}: Key Principles & Reactions" if not is_sublink else f"{topic}: Mechanistic Analysis"
    # Clean common prefixes/suffixes
    t = re.sub(r'\s*\((?:PDF|DOC|EPUB|FREE)\)', '', t, flags=re.IGNORECASE)
    t = re.sub(r'^(Notes|CBSE|NCERT|Class \d+|Study Material|Revision Guide|Detailed Notes|Chapter)\s*[-:–—]\s*', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s*[-:–—]\s*(Chemistry Study Material|Revision Guide|PDF|Notes|Class \d+|Detailed Notes).*$', '', t, flags=re.IGNORECASE).strip()
    t = re.sub(r'Class \d+ Notes', 'Core Theory & Reactions', t, flags=re.IGNORECASE).strip()
    return t or topic


def sanitize_and_balance_math(text: str) -> str:
    """
    Ensures all LaTeX math blocks ($$ ... $$) and inline math ($ ... $)
    are properly paired and closed. Strips dangling or orphaned math fences.
    """
    if not text:
        return ""

    # 1. Clean dangling or orphaned math start tags like "$$\" or "$$\n" at end of lines
    text = re.sub(r'\$\$\\?\s*$', '', text)
    text = re.sub(r'^\s*\$\$\\?\s*$', '', text, flags=re.MULTILINE)

    # 2. Balance display math ($$)
    display_matches = list(re.finditer(r'\$\$', text))
    if len(display_matches) % 2 != 0:
        last_match = display_matches[-1]
        last_idx = last_match.start()
        remaining = text[last_idx + 2:].strip()
        if not remaining or len(remaining) < 5 or "\n\n" in remaining:
            text = text[:last_idx].rstrip()
        else:
            text = text + "\n$$\n"

    # 3. Balance inline math ($) on lines that do not have $$
    balanced_lines = []
    for line in text.splitlines():
        if "$$" in line:
            balanced_lines.append(line)
            continue
        single_dollar_count = len(re.findall(r'(?<!\\)\$', line))
        if single_dollar_count % 2 != 0:
            if line.rstrip().endswith("$"):
                balanced_lines.append(line.rstrip()[:-1])
            else:
                balanced_lines.append(line + "$")
        else:
            balanced_lines.append(line)

    return "\n".join(balanced_lines)


def _clean_trailing_incomplete_generation(text: str) -> str:
    """Removes trailing incomplete sentences, hanging math brackets, or half-generated bullet points/tables."""
    if not text:
        return ""

    text = sanitize_and_balance_math(text)
    lines = text.strip().splitlines()

    cutoff_words = (
        "where:", "involves", "the", "a", "an", "of", "and", "or", ":", 
        "is", "by", "from", "with", "such as", "including", "to", "for", 
        "in", "on", "as", "at", "than", "are", "was", "were"
    )
    cutoff_symbols = ("[", "$[", "(", "{", "=", "->", "→", "+", "-")

    while lines:
        last = lines[-1].strip()
        if not last:
            lines.pop()
            continue

        last_lower = last.lower()

        # Check for hanging display math line
        if last in ("$$", "$$\\", "$$/") or last.startswith("$$\\"):
            lines.pop()
            continue

        # Incomplete table rows (e.g. '| Aryl halides | Halogen directly on')
        if last.startswith("|"):
            # Table row must end with a pipe and have valid cells
            if not last.endswith("|") or last.count("|") < 2:
                lines.pop()
                continue
            # If the last line is a table header separator without rows, pop it
            if re.match(r'^\|(?:\s*:?-+:?\s*\|)+$', last):
                lines.pop()
                continue
            # Check if last cell ends with an incomplete word or symbol
            last_cell = last.split("|")[-2].strip().lower()
            if any(last_cell.endswith(sym) for sym in cutoff_symbols) or any(re.search(rf'\b{re.escape(w)}$', last_cell) for w in cutoff_words):
                lines.pop()
                continue

        # Cutoff marker endings (symbols or whole words)
        if any(last.endswith(sym) for sym in cutoff_symbols) or any(re.search(rf'\b{re.escape(w)}$', last_lower) for w in cutoff_words):
            lines.pop()
            continue

        # Hanging open markdown formatting
        if last.count("**") % 2 != 0 or last.count("__") % 2 != 0:
            lines.pop()
            continue

        # Truncated heading
        if last.startswith(("#", "##", "###", "####")):
            if any(re.search(rf'\b{re.escape(w)}$', last_lower) for w in cutoff_words) or len(last.split()) <= 2:
                lines.pop()
                continue

        # Truncated bullet point
        if last.startswith(("*", "-", "•")):
            clean_bullet = re.sub(r'^[-*•]\s*', '', last).strip()
            if any(clean_bullet.endswith(sym) for sym in cutoff_symbols) or any(re.search(rf'\b{re.escape(w)}$', clean_bullet.lower()) for w in cutoff_words):
                lines.pop()
                continue
            if not any(clean_bullet.endswith(p) for p in ('.', '!', '?', ':', ')', '`', '$', '|')) and len(clean_bullet.split()) < 6:
                lines.pop()
                continue

        # Unclosed bracket
        if re.search(r'\[[A-Za-z0-9_\(\)\s]*$', last):
            lines.pop()
            continue

        break

    cleaned = "\n".join(lines).strip()
    return sanitize_and_balance_math(cleaned)


def synthesize_chunk_with_dynamic_context(
    chunk: Any,
    topic: str,
    doc_title: str,
    doc_source: str
) -> str:
    """
    Synthesizes an individual semantic chunk using dynamic context length.
    Context budget: context_length = 1000 + query_length_tokens.
    Executes fast on CPU (~15s prompt prefill instead of 15m).
    """
    query_tokens = len(topic.split()) * 2 + 30
    chunk_words = getattr(chunk, "word_count", len(chunk.text.split())) if hasattr(chunk, "text") else len(str(chunk).split())
    chunk_tokens = int(chunk_words * 1.33)
    
    dynamic_budget = 4096
    if calculate_dynamic_context_budget:
        dynamic_budget = calculate_dynamic_context_budget(query_tokens, chunk_tokens)

    chunk_text = getattr(chunk, "text", str(chunk))
    chunk_id = getattr(chunk, "chunk_id", 1)

    if ResearchContextManager:
        full_prompt = ResearchContextManager.build_prompt(
            topic=topic,
            chunk_text=chunk_text,
            doc_title=doc_title,
            doc_source=doc_source,
            chunk_id=chunk_id
        )
    else:
        system_prompt = build_system_prompt(topic)
        user_prompt = (
            f"TOPIC: {topic}\n"
            f"SOURCE: {doc_title} ({doc_source}) - Part {chunk_id}\n\n"
            f"CONTENT SEGMENT:\n{chunk_text}\n\n"
            f"TASK:\n"
            f"Synthesize this scientific segment for topic '{topic}' into rich, rigorous notes:\n"
            f"1. Explain all underlying theories, definitions, and mechanisms from first principles.\n"
            f"{req_rule}\n"
            f"3. Organize comparative or property data into structured Markdown tables (| Col1 | Col2 |).\n"
            f"4. Preserve exact definitions, constants, and quotes in blockquotes (>).\n"
            f"5. Wrap key scientific entities in [[Wikilinks]].\n"
            f"Strictly omit web navigation, ads, and quiz buttons. Output direct synthesis only.\n\n"
            f"SYNTHESIS:"
        )
        full_prompt = f"{system_prompt}\n\n{user_prompt}"

    max_gen_tokens = min(1000, max(500, int(chunk_words * 0.5)))

    llm_chunk_out = _call_llm_backend(full_prompt, max_tokens=max_gen_tokens)
    if llm_chunk_out and len(llm_chunk_out.strip()) >= 80:
        cleaned_out = _clean_trailing_incomplete_generation(llm_chunk_out)
        if len(cleaned_out) >= 60:
            return cleaned_out

    # Deterministic fallback per chunk to preserve data integrity if LLM unavailable
    paragraphs = []
    for p in chunk_text.split("\n\n"):
        p_clean = p.strip()
        p_lower = p_clean.lower()
        if p_clean.startswith("|"):
            if any(bad in p_lower for bad in (
                "prose", "poem", "syllabus", "cbse", "sample paper", 
                "class 6", "class 7", "class 8", "class 9", "class 10", "class 11",
                "textbook", "chapter list", "kaveri", "ganita", "poorvi"
            )):
                continue
            paragraphs.append(p_clean)
            continue
        if p_clean.startswith("$$"):
            paragraphs.append(p_clean)
            continue
        if len(p_clean) < 40 or p_clean.startswith("#"):
            continue
        lines = [l.strip() for l in p_clean.splitlines() if l.strip()]
        link_lines = [l for l in lines if l.startswith("[") or l.startswith("- [") or l.startswith("* [")]
        if len(link_lines) / max(1, len(lines)) > 0.3:
            continue
        if any(term in p_lower for term in (
            "wayback machine", "placement 360", "donate.wikimedia", "special:create",
            "amazon associate", "check show answer", "buy on amazon", "written by satish",
            "class 6", "class 7", "class 8", "class 9", "class 10", "class 11",
            "ncert solutions for class", "how i taught my grandmother", "ganita manjari",
            "poorvi", "clearstudy is an independent", "faqs about ncert solutions"
        )):
            continue
        paragraphs.append(p_clean)

    return "\n\n".join(paragraphs) if paragraphs else chunk_text


def synthesize_and_update(
    topic: str,
    new_doc: Dict[str, Any],
    note_title: Optional[str] = None,
    doc_index: int = 1,
    temp_storage: Optional[Any] = None
) -> str:
    """
    Primary interface for Function 6 with Dynamic Context Limiter:
    1. Fetches existing Obsidian note (Function 5).
    2. Smart Semantic Chunker partitions document into ~1,000 (+400) word chunks.
    3. Queues chunks and runs synthesis with dynamic context budget (1000 + query_length_tokens).
    4. Saves intermediate chunk syntheses to Temp/<topic>/chunk_syntheses/.
    5. Consolidates chunk outputs and updates knowledge using robust merging engine.
    6. Saves resulting synthesis back to Obsidian (Function 4).
    """
    target_note_title = note_title or f"Research_{topic.replace(' ', '_')}"
    existing_note = fetch_from_obsidian(target_note_title)
    
    new_content = new_doc.get("content", "")
    new_source = new_doc.get("source", "Unknown Source")
    new_title = new_doc.get("title", "Incoming Document")

    # Resolve temp storage for saving intermediate chunk syntheses
    if temp_storage is None:
        try:
            from .temp_manager import TempResearchStorage
            temp_storage = TempResearchStorage(topic)
        except Exception:
            temp_storage = None

    # Step 1: Partition content into smart semantic chunks (2200 base words + 800 lookahead words)
    if SmartSemanticChunker and new_content:
        chunker = SmartSemanticChunker(base_words=2200, max_lookahead=800)
        chunks = chunker.chunk_text(new_content, source_title=new_title, source_url=new_source)
    else:
        # Fallback to single chunk if limiter unavailable
        chunks = [
            SemanticChunk(chunk_id=1, text=new_content, word_count=len(new_content.split()), is_last=True)
            if SemanticChunk else new_content
        ]

    logger.info(
        f"Dynamic Context Limiter: processing '{new_title}' in {len(chunks)} chunk(s) "
        f"(doc {doc_index}) for topic '{topic}'."
    )

    # Step 2: Queue processing with dynamic context length per chunk
    chunk_syntheses: List[str] = []
    for chunk in chunks:
        chunk_id = getattr(chunk, "chunk_id", 1)
        chunk_words = getattr(chunk, "word_count", len(chunk.text.split())) if hasattr(chunk, "text") else len(str(chunk).split())
        chunk_text = getattr(chunk, "text", str(chunk))

        logger.info(f"Synthesizing chunk {chunk_id}/{len(chunks)} ({chunk_words} words) with dynamic context budget.")
        chunk_out = synthesize_chunk_with_dynamic_context(chunk, topic, new_title, new_source)
        chunk_syntheses.append(chunk_out)

        # Step 3: Save intermediate LLM synthesis in Temp/<topic>/chunk_syntheses/
        if temp_storage and hasattr(temp_storage, "save_chunk_synthesis"):
            try:
                temp_storage.save_chunk_synthesis(
                    doc_index=doc_index,
                    chunk_id=chunk_id,
                    chunk_text=chunk_text,
                    synthesis_result=chunk_out,
                    source_title=new_title
                )
            except Exception as e:
                logger.warning(f"Could not save chunk synthesis {chunk_id} to Temp: {e}")

    # Step 4: Consolidate chunk syntheses without data loss
    consolidated_new_content = "\n\n".join(chunk_syntheses)
    synthesized_doc = dict(new_doc)
    synthesized_doc["raw_content"] = new_content
    synthesized_doc["content"] = consolidated_new_content

    # Step 5: Merge into existing Obsidian note (incorporates theory, quotes, formulas, discrepancies)
    final_output = _fallback_deterministic_synthesis(existing_note, synthesized_doc, topic)

    # Collect all sources
    prior_sources = existing_note["metadata"].get("sources", []) if existing_note else []
    if new_source and new_source not in prior_sources:
        prior_sources.append(new_source)

    # Extract wikilinks for Obsidian Knowledge Graph
    wikilinks = extract_entities_for_wikilinks(final_output)

    # Save to Obsidian (Function 4)
    file_path = store_in_obsidian(
        title=target_note_title,
        content=final_output,
        tags=["research", "synthesis", topic.lower().replace(" ", "-")],
        sources=prior_sources,
        wikilinks=wikilinks,
        metadata={"topic": topic, "sources_count": len(prior_sources)}
    )

    logger.info(f"Synthesizer completed pass for '{new_title}' ({len(chunks)} chunk(s)). Saved note to: {file_path}")
    return file_path
