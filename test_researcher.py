"""
Unit tests for Researcher module.
Verifies all functions, deep crawling, temp staging, noise filtering, and iterative workflow.
"""

import os
import shutil
import tempfile
import unittest

from Researcher.collector import clean_url, is_valid_url, filter_relevant_sublinks
from Researcher.cleaner import format_research_note, strip_html_tags, extract_referenced_links
from Researcher.temp_manager import TempResearchStorage
from Researcher.obsidian import ObsidianVault
from Researcher.synthesizer import synthesize_and_update
from Researcher.showcase import generate_web_view
from Researcher.pipeline import ResearchPipeline


class TestResearcherModule(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.vault = ObsidianVault(vault_path=os.path.join(self.test_dir, "TestVault"))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_function_1_collector_url_logic(self):
        valid = is_valid_url("https://example.com/research")
        invalid = is_valid_url("not_a_url")
        self.assertTrue(valid)
        self.assertFalse(invalid)

        cleaned = clean_url("https://example.com/page?utm_source=twitter&keep=1")
        self.assertIn("keep=1", cleaned)
        self.assertNotIn("utm_source", cleaned)

    def test_function_1_sublink_relevance_filter(self):
        links = [
            {"title": "Faraday's Law of Induction", "url": "https://example.com/physics/faradays-law"},
            {"title": "Lenz's Law and Magnetic Flux", "url": "https://example.com/physics/lenzs-law"},
            {"title": "GeeksforGeeks Jobs and Careers", "url": "https://example.com/jobs"},
            {"title": "Sign In to Account", "url": "https://example.com/login"},
            {"title": "School Resources Biology Class", "url": "https://example.com/biology"}
        ]
        filtered = filter_relevant_sublinks(links, topic="ElectroMagnetic Induction", max_links=2)
        self.assertEqual(len(filtered), 2)
        urls = [item["url"] for item in filtered]
        self.assertIn("https://example.com/physics/faradays-law", urls)
        self.assertIn("https://example.com/physics/lenzs-law", urls)
        self.assertNotIn("https://example.com/jobs", urls)

    def test_function_3_cleaner(self):
        sample_html = """
        <html>
            <head><title>Quantum Computing Milestone</title></head>
            <body>
                <nav><a href="#">Menu</a></nav>
                <h1>Quantum Computing Milestone</h1>
                <p>Researchers achieved a <strong>breakthrough</strong> in error correction.</p>
                <blockquote>"This changes everything." - Lead Physicist</blockquote>
                <footer>Footer text</footer>
            </body>
        </html>
        """
        doc = format_research_note(sample_html, source_url="https://phys.org/test")
        self.assertEqual(doc["title"], "Quantum Computing Milestone")
        self.assertIn("breakthrough", doc["content"])
        self.assertNotIn("Footer text", doc["content"])
        self.assertIn("> \"This changes everything.\"", doc["content"])

    def test_function_3_strips_nav_trash_from_prompt(self):
        trash_input = """
        # Electromagnetic Induction
        [![geeksforgeeks](https://media.geeksforgeeks.org/gfg-gg-logo.svg)](https://www.geeksforgeeks.org/)

        - Courses
        **
        - Tutorials
        **
        - Practice
        **
        - Jobs
        **

        **Switch to Dark Mode

        Sign In

        - [Physics](https://www.geeksforgeeks.org/physics/physics/)
        - [Acoustics](https://www.geeksforgeeks.org/physics/acoustics/)
        - [Kinematics](https://www.geeksforgeeks.org/physics/what-is-kinematics/)
        - [Wave Theory](https://www.geeksforgeeks.org/physics/waves/)
        - [Electromagnetic Induction](https://www.geeksforgeeks.org/physics/electromagnetic-induction/)
        - [Biology](https://www.geeksforgeeks.org/biology/biology/)
        - [Chemistry](https://www.geeksforgeeks.org/chemistry/chemistry/)

        Electromagnetic induction is a process in which a conductor is put in a particular position and magnetic field varies.
        """
        doc = format_research_note(trash_input, source_url="https://www.geeksforgeeks.org/physics/electromagnetic-induction/")
        content = doc["content"]
        self.assertNotIn("Courses", content)
        self.assertNotIn("Switch to Dark Mode", content)
        self.assertNotIn("Sign In", content)
        self.assertNotIn("gfg-gg-logo.svg", content)
        self.assertIn("Electromagnetic induction is a process", content)

    def test_showcase_markdown_to_html_formatting(self):
        from Researcher.showcase import markdown_to_html_enhanced
        md = """
        ## Core Physics
        - **Bold bullet**: This is *italic* and [[Quantum Theory]].
        - See [Docs](https://example.com).

        $$E = mc^2$$
        """
        res = markdown_to_html_enhanced(md)
        self.assertIn("<strong>Bold bullet</strong>", res)
        self.assertIn("<em>italic</em>", res)
        self.assertIn('<span class="wikilink">Quantum Theory</span>', res)
        self.assertIn('<a href="https://example.com"', res)
        self.assertIn('<div class="formula-box">$$E = mc^2$$</div>', res)
        self.assertIn('<div class="content-card">', res)

    def test_temp_storage_manager(self):
        temp_mgr = TempResearchStorage("Test_Topic_Alpha")
        try:
            temp_mgr.clear()
            doc1 = {"title": "Doc 1", "content": "Theory body 1", "word_count": 100}
            doc2 = {"title": "Doc 2", "content": "Theory body 2", "word_count": 200}

            temp_mgr.save_page_data(1, "https://example.com/main", "Doc 1", "raw1", doc1, is_sublink=False)
            temp_mgr.save_page_data(2, "https://example.com/sub", "Doc 2", "raw2", doc2, is_sublink=True)

            staged = temp_mgr.load_all_staged()
            self.assertEqual(len(staged), 2)
            # Main comes first
            self.assertFalse(staged[0]["is_sublink"])
            self.assertTrue(staged[1]["is_sublink"])
        finally:
            temp_mgr.clear()

    def test_functions_4_5_7_obsidian_vault(self):
        # Function 4: Store with thread lock
        note_path = self.vault.store_note(
            title="Quantum_Test",
            content="## Key Facts\nQuantum bits utilize superposition.",
            tags=["quantum", "physics"],
            sources=["https://phys.org/test"],
            wikilinks=["Qubits", "Superposition", "Dark Mode\n\nSign In", "Web Source"]
        )
        self.assertTrue(os.path.isfile(note_path))

        # Store a second time: ensure Related Entities is NOT duplicated and junk is filtered
        note_path = self.vault.store_note(
            title="Quantum_Test",
            content=self.vault.fetch_note("Quantum_Test")["content"] + "\n\nUpdated findings on quantum circuits.",
            tags=["quantum", "physics"],
            sources=["https://phys.org/test"],
            wikilinks=["Qubits", "Superposition", "Quantum Circuits"]
        )
        with open(note_path, "r", encoding="utf-8") as f:
            saved_content = f.read()
            self.assertEqual(saved_content.count("## Related Entities"), 1)
            self.assertNotIn("Dark Mode", saved_content)
            self.assertNotIn("Web Source", saved_content)
            self.assertIn("[[Quantum Circuits]]", saved_content)
            self.assertIn("[[Superposition]]", saved_content)

        # Function 5: Fetch note
        fetched = self.vault.fetch_note("Quantum_Test")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["title"], "Quantum_Test")
        self.assertIn("Superposition", fetched["wikilinks"])

        # Function 7: Global listing & query
        all_notes = self.vault.list_notes()
        self.assertIn("Quantum_Test", all_notes)

        search_results = self.vault.query_vault("superposition")
        self.assertEqual(len(search_results), 1)

    def test_function_6_iterative_synthesis_and_discrepancies(self):
        from Researcher import obsidian
        original_vault = obsidian._DEFAULT_VAULT
        obsidian._DEFAULT_VAULT = self.vault

        try:
            # Source 1: Founded in 2010
            doc1 = {
                "title": "Alpha Research",
                "source": "https://alpha.org/study",
                "content": "> \"Founded in 2010 with $50M seed round.\"\nThe project expanded rapidly."
            }
            synthesize_and_update("AI History", doc1, note_title="AI_History")

            # Verify note 1 saved
            n1 = self.vault.fetch_note("AI_History")
            self.assertIsNotNone(n1)
            self.assertIn("2010", n1["content"])

            # Source 2: Contradictory date - Founded in 2015
            doc2 = {
                "title": "Beta Archives",
                "source": "https://beta.org/history",
                "content": "> \"Founded in 2015 with $12M grant.\"\nArchival records refute earlier dates."
            }
            synthesize_and_update("AI History", doc2, note_title="AI_History")

            # Verify note updated with Discrepancies and Quote preservation
            n2 = self.vault.fetch_note("AI_History")
            self.assertIsNotNone(n2)
            self.assertIn("## Discrepancies", n2["content"])
            self.assertIn("> \"Founded", n2["content"])

            # Test Showcase Web View and PDF generation
            reports = generate_web_view("AI_History", auto_open=False, create_pdf=True)
            self.assertTrue(os.path.isfile(reports["html"]))
            self.assertTrue(os.path.isfile(reports["pdf"]))

            # Verify HTML readability, bold rendering, and quotes exclusion
            with open(reports["html"], "r", encoding="utf-8") as f:
                html_content = f.read()
                self.assertIn("font-size: 15px", html_content)
                self.assertIn("content-card", html_content)
                self.assertIn("subtopics-grid", html_content)
                self.assertNotIn("## Primary Source Quotes", html_content)
                self.assertNotIn('<span class="badge tag">', html_content)
        finally:
            obsidian._DEFAULT_VAULT = original_vault


if __name__ == "__main__":
    unittest.main()
