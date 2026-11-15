"""
llm_manager.py - Dedicated LLM Manager for Researcher Subsystem
Manages SmolLM2-1.7B-Instruct-GGUF (q8_0) with 8192 context window.

Key Features:
1. Smart persistent loading: loads LLM once for entire research run, keeps warm across iterations.
2. Unloads cleanly and runs garbage collection after research finishes to free ~2GB RAM.
3. Context Manager: builds ChatML prompts, enforces scientific safeguards, LaTeX formatting, and cleans web input.
4. Synthesizer: runs inference with temperature=0.2 and min_p=0.05, post-processing formulas and text.
"""

import os
import sys
import gc
import re
from typing import Optional, Dict, Any, List

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


MODEL_FILENAME = "SmolLM2-1.7B-Instruct-Q8_0.gguf"
REPO_ID = "bartowski/SmolLM2-1.7B-Instruct-GGUF"


def get_model_path() -> Optional[str]:
    """Resolves path to SmolLM2 GGUF file in Researcher/models/ or system cache."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    local_path = os.path.join(base_dir, "models", MODEL_FILENAME)
    if os.path.exists(local_path):
        return local_path

    # Check env override
    env_path = os.environ.get("RESEARCHER_MODEL_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    # Check Hugging Face hub cache
    try:
        from huggingface_hub import try_to_load_from_cache
        cached = try_to_load_from_cache(repo_id=REPO_ID, filename=MODEL_FILENAME)
        if isinstance(cached, str) and os.path.exists(cached):
            return cached
    except Exception:
        pass

    return local_path


class ResearcherLLM:
    """
    Singleton manager for the Researcher's dedicated LLM instance.
    Keeps the model loaded in RAM throughout all research iterations,
    then unloads cleanly upon completion to return memory to the system.
    """
    _instance: Optional["ResearcherLLM"] = None
    _model: Optional[Any] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ResearcherLLM, cls).__new__(cls)
            cls._instance._model = None
        return cls._instance

    @classmethod
    def get_instance(cls) -> "ResearcherLLM":
        if cls._instance is None:
            cls._instance = ResearcherLLM()
        return cls._instance

    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> Optional[Any]:
        """Loads SmolLM2 into RAM with configured 8192 context if not already loaded."""
        if self._model is not None:
            return self._model

        model_path = get_model_path()
        if not model_path or not os.path.exists(model_path):
            logger.warning(
                f"SmolLM2 model not found at '{model_path}'. "
                f"Run `python Researcher/download_model.py` to download it."
            )
            return None

        try:
            import llama_cpp
        except ImportError:
            logger.error("llama_cpp library not available in Python environment.")
            return None

        logger.info(
            f"Loading dedicated Researcher LLM (SmolLM2-1.7B Q8_0) from {model_path} "
            f"[n_ctx=8192, n_batch=1024, n_threads=4, type_k=Q8_0, type_v=Q8_0, flash_attn=True]..."
        )

        try:
            self._model = llama_cpp.Llama(
                model_path=model_path,
                n_ctx=8192,
                n_batch=1024,
                n_threads=4,
                type_k=llama_cpp.GGML_TYPE_Q8_0,
                type_v=llama_cpp.GGML_TYPE_Q8_0,
                flash_attn=True,
                verbose=False
            )
            logger.info("Researcher LLM successfully loaded into memory and ready for research.")
            return self._model
        except Exception as e:
            logger.error(f"Failed to load SmolLM2 model: {e}")
            self._model = None
            return None

    def unload(self) -> None:
        """Unloads model from RAM and frees memory for ALFRED."""
        if self._model is not None:
            logger.info("Unloading Researcher LLM from RAM...")
            del self._model
            self._model = None
            gc.collect()
            logger.info("Researcher LLM unloaded. Memory freed.")

    def __enter__(self):
        self.load()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.unload()


def get_researcher_llm() -> Optional[Any]:
    """Helper to acquire loaded model from singleton."""
    return ResearcherLLM.get_instance().load()


def unload_researcher_llm() -> None:
    """Helper to unload model singleton."""
    ResearcherLLM.get_instance().unload()


class ResearchContextManager:
    """
    Handles prompt engineering, ChatML formatting, domain safeguards,
    LaTeX enforcement, and web content sanitization for Researcher.
    """

    @staticmethod
    def build_system_prompt(topic: str = "") -> str:
        """Constructs strict domain instructions with mathematical and scientific guardrails."""
        topic_lower = topic.lower()

        domain_guidance = ""
        if any(k in topic_lower for k in ("chem", "coordination", "compound", "reaction", "biomolecule", "amino", "protein", "carbohydrate", "acid", "ligand", "haloalkane", "haloarene")):
            domain_guidance = (
                "   - Format all chemical formulas, complexes, zwitterions, and reaction mechanisms in standard LaTeX ($...$ and $$...$$).\n"
                "   - Properly format subscripts, charges, and oxidation states (e.g. $[Co(NH_3)_6]^{3+}$, $C_6H_{12}O_6$, $R-CH(NH_3^+)COO^-$).\n"
            )
        elif any(k in topic_lower for k in ("electromagnetic", "induction", "physics", "magnetic", "electric", "optics", "quantum", "mechanics")):
            domain_guidance = (
                "   - Format all physical equations, vector fields, and conservation laws in standard LaTeX ($...$ and $$...$$).\n"
                "   - Properly format differential and integral equations (e.g. Faraday's law $\\mathcal{E} = -\\frac{d\\Phi_B}{dt}$, flux $\\Phi_B = \\iint \\mathbf{B} \\cdot d\\mathbf{A}$).\n"
            )
        else:
            domain_guidance = (
                "   - Format all mathematical formulations, quantitative definitions, and formulas in standard LaTeX ($...$ and $$...$$).\n"
            )

        return (
            "You are an expert Research Synthesizer and Senior Science Academic specializing in deep textual analysis.\n"
            "Your task is to iteratively synthesize incoming scientific research into rich, rigorous notes.\n\n"
            "CRITICAL SCIENTIFIC & FORMATTING RULES (NON-NEGOTIABLE):\n"
            "1. STRICT DOMAIN RELEVANCE (ZERO OFF-TOPIC JUNK):\n"
            f"   - Synthesize ONLY concepts, theories, empirical data, and mechanisms directly related to the research TOPIC: '{topic}'.\n"
            "   - Discard all website navigation, syllabus directories, school grade indexes, chapter catalogs, prose, commercial ads, test questions, and FAQs.\n"
            "2. SCIENTIFIC & MATHEMATICAL RIGOR:\n"
            "   - Always use standard LaTeX for all scientific symbols and mathematical equations.\n"
            f"{domain_guidance}"
            "   - Write multi-term equations in display math ($$ ... $$) and inline formulas in ($ ... $).\n"
            "   - State definitions of variables, units, and boundary conditions.\n"
            "3. HIGH DATA FIDELITY & TABLES:\n"
            "   - Format genuine scientific classifications, property comparisons, and empirical data using Markdown tables (| Col1 | Col2 |).\n"
            "4. FIRST PRINCIPLES & MECHANISMS:\n"
            "   - Fully explain underlying theories, governing physical laws, reaction pathways, or biological mechanisms from first principles.\n"
            "5. ZERO DATA LOSS & NO AD/UI NOISE:\n"
            "   - Do not omit key scientific facts, empirical observations, or formulas.\n"
            "   - Never include website navigation, subscription links, affiliate text, or test buttons.\n"
            "6. QUOTE PRESERVATION: Preserve key empirical statements and definitions in Markdown blockquotes (>).\n"
            "7. OBSIDIAN LINKING: Wrap core topic concepts, specific scientific entities, and fundamental laws in [[Wikilinks]]."
        )

    @staticmethod
    def build_prompt(
        topic: str,
        chunk_text: str,
        doc_title: str,
        doc_source: str,
        chunk_id: int = 1
    ) -> str:
        """
        Constructs full ChatML prompt (<|im_start|>) for SmolLM2 Instruct:
        Safeguards + Cleaned Web Segment -> Model Prompt.
        """
        system_content = ResearchContextManager.build_system_prompt(topic)

        user_content = (
            f"TOPIC: {topic}\n"
            f"SOURCE: {doc_title} ({doc_source}) - Part {chunk_id}\n\n"
            f"CONTENT SEGMENT:\n{chunk_text}\n\n"
            f"TASK:\n"
            f"Synthesize this scientific segment for topic '{topic}' into rich, rigorous notes:\n"
            f"1. Explain all underlying theories, definitions, and mechanisms from first principles.\n"
            f"2. Write all formulas and equations in accurate LaTeX ($...$ and $$...$$).\n"
            f"3. Organize comparative or property data into structured Markdown tables (| Col1 | Col2 |).\n"
            f"4. Preserve exact definitions, constants, and quotes in blockquotes (>).\n"
            f"5. Wrap key scientific entities in [[Wikilinks]].\n"
            f"Strictly omit web navigation, ads, and quiz buttons. Output direct synthesis only.\n\n"
            f"SYNTHESIS:"
        )

        return (
            f"<|im_start|>system\n{system_content}<|im_end|>\n"
            f"<|im_start|>user\n{user_content}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )


class ResearchSynthesizer:
    """
    Executes inference against the persistent SmolLM2 instance using specified sampling parameters.
    """

    def __init__(self, llm_manager: Optional[ResearcherLLM] = None):
        self.manager = llm_manager or ResearcherLLM.get_instance()

    def synthesize(
        self,
        prompt: str,
        max_tokens: int = 1200
    ) -> Optional[str]:
        """
        Queries SmolLM2 with temperature=0.2, min_p=0.05, and cleans formatting.
        """
        model = self.manager.get_instance().load()
        if not model:
            logger.debug("SmolLM2 instance not loaded. Cannot execute LLM synthesis.")
            return None

        stop_tokens = [ 
            "<|im_end|>", "<|im_start|>", "</s>", "User:",
            "\n\n\n\n", "### Notes", "#### Notes", "### References",
            "#### References", "## References", "## Notes"
        ]

        try:
            # Safeguard context window limits against n_ctx=8192
            n_ctx = 8192
            tokenized = model.tokenize(prompt.encode("utf-8")) if hasattr(model, "tokenize") else []
            prompt_tokens = len(tokenized) if tokenized else int(len(prompt.split()) * 1.35)
            
            allowed_max_tokens = max(128, min(max_tokens, n_ctx - prompt_tokens - 64))
            if prompt_tokens + 128 > n_ctx:
                # If prompt alone exceeds context window, safely truncate prompt
                safe_char_len = int((n_ctx - 512) * 2.8)
                prompt = prompt[:safe_char_len]
                allowed_max_tokens = 512

            logger.info(f"Synthesizer calling SmolLM2 [max_tokens={allowed_max_tokens}, prompt_tokens~={prompt_tokens}, temp=0.2, min_p=0.05]...")
            out = model(
                prompt,
                max_tokens=allowed_max_tokens,
                temperature=0.2,
                min_p=0.05,
                stop=stop_tokens,
                echo=False
            )
            raw_text = out["choices"][0]["text"].strip()
            if not raw_text:
                return None

            # Clean trailing cutoffs and balance math
            from .synthesizer import _clean_trailing_incomplete_generation
            cleaned = _clean_trailing_incomplete_generation(raw_text)
            return cleaned if cleaned else raw_text

        except Exception as e:
            logger.error(f"Error during SmolLM2 inference: {e}")
            return None
