"""Relationship scope tags (user decision C, 2026-10-17): chain edges are "ai", relations/ rows become separate
"other" edges, and nothing the build reads is ever changed or dropped.

    python -X utf8 -m unittest discover -s tests/graph -t .
"""
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import graph_build
import relations
from utils import check_relations

# A two-company chain: Alpha (GPU) supplies Beta (cloud) with one recorded contract.
CHAIN = {
    "company": "Alpha",
    "chain_focus": "test chain",
    "flow": [
        {"layer": "cloud_infra", "sectors": [{"sector": "Hyperscaler", "players": [
            {"company": "Beta", "product": "GPU cloud", "connects_to": [], "quarterly_data": []}]}]},
        {"layer": "compute_hardware", "sectors": [{"sector": "GPU", "players": [
            {"company": "Alpha", "product": "Alpha GPU", "quarterly_data": [],
             "connects_to": [{"company": "Beta", "relationship": "GPU supply", "contracts": [
                 {"source": "Alpha Q1 FY2027 (05-01-2026)", "signal": "Beta buys Alpha GPUs", "units": "1M",
                  "value": "no specific figure", "date_signed": "2026", "type": "purchase", "topics": []}]}]}]}]},
    ],
}


def row(frm, to, relation, product, label="Alpha 10-K (02-14-2026)", date="2026-02-14", **extra):
    """One relations row with every required key (the values the tests do not care about are fixed)."""
    out = {"from": frm, "to": to, "relation": relation, "product": product, "scope": "other",
           "source": "transcripts/edgar/alpha_10-K.txt", "quote": "Alpha sells mining trucks to Rio Tinto.",
           "label": label, "date": date, "added": "2026-10-17"}
    out.update(extra)
    return out


class TempRepoTestCase(unittest.TestCase):
    """Each test runs in a fresh temporary folder holding chains/test.json (graph_build reads relative paths)."""

    def setUp(self):
        self.old_cwd = os.getcwd()
        self.tmp = tempfile.mkdtemp(prefix="relations_test_")
        os.chdir(self.tmp)
        os.makedirs("chains")
        self.write("chains/test.json", CHAIN)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.tmp)

    def write(self, path, data):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def build(self):
        """graph_build.build_graph without its progress lines; returns (graph, printed text)."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            graph = graph_build.build_graph()
        return graph, out.getvalue()


class ScopeTagTest(TempRepoTestCase):
    def test_chain_edges_default_to_ai_and_no_relations_means_no_other_edges(self):
        graph, _ = self.build()
        self.assertEqual(len(graph["edges"]), 1)
        edge = graph["edges"][0]
        self.assertEqual((edge["source"], edge["target"], edge["scope"]), ("Alpha", "Beta", "ai"))
        self.assertEqual(edge["chain"], "test")
        self.assertEqual(graph["other_edges"], [])
        # the file on disk has the same three keys
        with open("graph/merged_graph.json", encoding="utf-8") as f:
            self.assertEqual(list(json.load(f)), ["nodes", "edges", "other_edges"])

    def test_other_edges_stay_out_of_edges(self):
        without, _ = self.build()
        self.write("relations/alpha.json", {"company": "Alpha", "relations": [
            row("Alpha", "Rio Tinto", "supplies", "mining trucks"),
            row("Alpha", "Gamma Steel", "customer_of", "steel plate"),
        ]})
        graph, _ = self.build()
        # what derive.py / evidence.py / enrich_status.py / verify_graph.py read is unchanged
        self.assertEqual(graph["edges"], without["edges"])
        self.assertEqual(graph["nodes"], without["nodes"])
        self.assertEqual(len(graph["other_edges"]), 2)
        self.assertTrue(all(e["scope"] == "other" for e in graph["other_edges"]))
        trucks, steel = graph["other_edges"]
        self.assertEqual((trucks["source"], trucks["target"], trucks["relation"]), ("Alpha", "Rio Tinto", "supplies"))
        # "Alpha customer_of Gamma Steel" points supplier -> customer like a chain edge: Gamma Steel -> Alpha
        self.assertEqual((steel["source"], steel["target"], steel["relation"]), ("Gamma Steel", "Alpha", "supplies"))
        self.assertEqual(steel["relationship"], "steel plate")
        self.assertEqual(steel["refs"][0]["label"], "Alpha 10-K (02-14-2026)")

    def test_relation_between_two_chain_companies_does_not_touch_the_ai_edge(self):
        self.write("relations/alpha.json", {"company": "Alpha", "relations": [
            row("Alpha", "Beta", "supplies", "office HVAC service")]})
        graph, _ = self.build()
        self.assertEqual(len(graph["edges"]), 1)
        ai = graph["edges"][0]
        self.assertEqual(ai["relationship"], "GPU supply")
        self.assertEqual(len(ai["contracts"]), 1)
        self.assertEqual(ai["scope"], "ai")
        self.assertEqual([(e["source"], e["target"], e["relationship"]) for e in graph["other_edges"]],
                         [("Alpha", "Beta", "office HVAC service")])

    def test_one_relationship_written_by_both_companies_is_one_edge_with_two_sources(self):
        self.write("relations/alpha.json", {"company": "Alpha", "relations": [
            row("Alpha", "Delta", "supplies", "mining trucks")]})
        self.write("relations/delta.json", {"company": "Delta", "relations": [
            row("Delta", "Alpha", "customer_of", "mining trucks", label="Delta 10-K (03-01-2026)", date="2026-03-01")]})
        graph, _ = self.build()
        self.assertEqual(len(graph["other_edges"]), 1)
        edge = graph["other_edges"][0]
        self.assertEqual((edge["source"], edge["target"]), ("Alpha", "Delta"))
        self.assertEqual([r["label"] for r in edge["refs"]], ["Alpha 10-K (02-14-2026)", "Delta 10-K (03-01-2026)"])

    def test_both_sides_with_their_own_product_wording_are_still_one_edge(self):
        # Each filer words the product its own way; the pair + relation decides, each ref keeps its wording.
        self.write("relations/vertiv.json", {"company": "Vertiv", "relations": [
            row("Vertiv", "Caterpillar", "customer_of", "diesel generator sets",
                label="Vertiv 10-K (02-20-2026)", date="2026-02-20")]})
        self.write("relations/caterpillar.json", {"company": "Caterpillar", "relations": [
            row("Caterpillar", "Vertiv", "supplies", "Cat C175 generator sets for data centers",
                label="Caterpillar 10-K (02-14-2026)", date="2026-02-14")]})
        graph, _ = self.build()
        self.assertEqual(len(graph["other_edges"]), 1)
        edge = graph["other_edges"][0]
        self.assertEqual((edge["source"], edge["target"], edge["relation"]), ("Caterpillar", "Vertiv", "supplies"))
        # files are read A->Z: caterpillar.json first, so its wording is the edge's relationship
        self.assertEqual(edge["relationship"], "Cat C175 generator sets for data centers")
        self.assertEqual([r["product"] for r in edge["refs"]],
                         ["Cat C175 generator sets for data centers", "diesel generator sets"])

    def test_fab_contractor_rows_never_reach_the_graph(self):
        # rule B holds even when check_relations.py was skipped
        self.write("relations/alpha.json", {"company": "Alpha", "relations": [
            row("Alpha", "Marketech", "customer_of", "cleanroom build-out"),
            row("Alpha", "Rio Tinto", "supplies", "mining trucks")]})
        graph, printed = self.build()
        self.assertEqual([e["target"] for e in graph["other_edges"]], ["Rio Tinto"])
        self.assertIn("semiconductor-fab contractor", printed)

    def test_partners_are_one_edge_whichever_side_wrote_it(self):
        self.write("relations/alpha.json", {"company": "Alpha", "relations": [
            row("Alpha", "Zeta", "partner", "joint engine development")]})
        self.write("relations/zeta.json", {"company": "Zeta", "relations": [
            row("Zeta", "Alpha", "partner", "joint engine development", label="Zeta 20-F (04-01-2026)", date="2026-04-01")]})
        graph, _ = self.build()
        self.assertEqual(len(graph["other_edges"]), 1)
        self.assertEqual(len(graph["other_edges"][0]["refs"]), 2)

    def test_bad_rows_and_broken_files_are_left_out_without_stopping_the_build(self):
        self.write("relations/alpha.json", {"company": "Alpha", "relations": [
            row("Alpha", "Rio Tinto", "supplies", "mining trucks"),
            row("Alpha", "Beta", "supplies", "GPUs", scope="ai"),          # AI belongs in a chain
            row("Alpha", "Omega Fund", "invests_in", "shares"),             # not a relation word
        ]})
        with open("relations/broken.json", "w", encoding="utf-8") as f:
            f.write("{ not json")
        graph, printed = self.build()
        self.assertEqual([e["target"] for e in graph["other_edges"]], ["Rio Tinto"])
        self.assertIn("broken.json skipped", printed)
        self.assertEqual(printed.count("left out of the graph"), 2)

    def test_the_build_never_changes_its_inputs(self):
        self.write("relations/alpha.json", {"company": "Alpha", "relations": [
            row("Alpha", "Rio Tinto", "supplies", "mining trucks")]})
        before = {p: Path(p).read_bytes() for p in ("chains/test.json", "relations/alpha.json")}
        self.build()
        self.build()                                                        # twice: idempotent too
        self.assertEqual({p: Path(p).read_bytes() for p in before}, before)
        self.assertEqual(sorted(os.listdir("relations")), ["alpha.json"])


class BackfillQueueTest(unittest.TestCase):
    GRAPH = {"nodes": [{"id": n} for n in ("Hub", "Leaf", "Mid", "Alone")],
             "edges": [{"source": "Hub", "target": "Mid"}, {"source": "Hub", "target": "Leaf"},
                       {"source": "Mid", "target": "Leaf"}, {"source": "Hub", "target": "Outside"}]}

    def test_queue_is_most_connected_first_then_a_to_z(self):
        queue = relations.build_queue(self.GRAPH, today="2026-10-17")
        self.assertEqual([r["company"] for r in queue["rows"]], ["Hub", "Leaf", "Mid", "Alone"])
        self.assertEqual([r["degree"] for r in queue["rows"]], [3, 2, 2, 0])
        self.assertTrue(all(r["status"] == "pending" and r["done_date"] is None for r in queue["rows"]))
        self.assertEqual(relations.next_pending(queue, 2), ["Hub", "Leaf"])

    def test_done_is_add_only(self):
        queue = relations.build_queue(self.GRAPH, today="2026-10-17")
        relations.mark_done(queue, ["Hub"], today="2026-10-17")
        relations.mark_done(queue, ["Hub", "Newco"], today="2026-10-18")   # Hub again; Newco not queued
        rows = {r["company"]: r for r in queue["rows"]}
        self.assertEqual((rows["Hub"]["status"], rows["Hub"]["done_date"]), ("done", "2026-10-17"))
        self.assertEqual((rows["Newco"]["status"], rows["Newco"]["done_date"]), ("done", "2026-10-18"))
        self.assertEqual(relations.next_pending(queue, 5), ["Leaf", "Mid", "Alone"])
        # rebuilding keeps every row, its order and status, and appends only new companies
        bigger = {"nodes": self.GRAPH["nodes"] + [{"id": "Later"}], "edges": self.GRAPH["edges"]}
        queue = relations.build_queue(bigger, queue)
        self.assertEqual([r["company"] for r in queue["rows"]], ["Hub", "Leaf", "Mid", "Alone", "Newco", "Later"])
        self.assertEqual(queue["rows"][0]["status"], "done")

    def test_queue_file_round_trip(self):
        tmp = tempfile.mkdtemp(prefix="relations_queue_")
        try:
            path = os.path.join(tmp, "q.json")
            queue = relations.build_queue(self.GRAPH, today="2026-10-17")
            relations.write_queue(queue, path)
            self.assertEqual(relations.read_queue(path), queue)
        finally:
            shutil.rmtree(tmp)


class CheckRelationsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="relations_check_"))
        (self.tmp / "transcripts" / "edgar").mkdir(parents=True)
        (self.tmp / "transcripts" / "edgar" / "alpha_10-K.txt").write_text(
            "Item 1.\nAlpha sells mining trucks\n  to Rio Tinto.\n", encoding="utf-8")
        self.ctx = {"root": self.tmp, "nodes": {"Alpha", "Beta"}, "metadata": {"Alpha", "Beta"},
                    "ai_pairs": {"Alpha": {"Beta"}, "Beta": {"Alpha"}},
                    "node_by_squash": {"alpha": "Alpha", "beta": "Beta"}}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def check(self, rows, baseline=None):
        data = {"company": "Alpha", "relations": rows}
        return check_relations.check_file("relations/alpha.json", data, baseline, self.ctx, "2026-10-17")

    def levels(self, found):
        return [level for level, _ in found]

    def test_a_valid_row_is_clean(self):
        # the quote spans a line break in the saved file: whitespace runs may differ
        self.assertEqual(self.check([row("Alpha", "Rio Tinto", "supplies", "mining trucks")]), [])

    def test_quote_must_be_in_the_saved_source(self):
        found = self.check([row("Alpha", "Rio Tinto", "supplies", "mining trucks", quote="Alpha sells ships.")])
        self.assertEqual(self.levels(found), ["FAIL"])

    def test_source_must_be_a_saved_file_or_a_public_url(self):
        url = row("Alpha", "Rio Tinto", "supplies", "mining trucks", source="https://example.com/10-K")
        memory = row("Alpha", "Rio Tinto", "supplies", "mining trucks", source="model knowledge")
        # a URL row is accepted but always listed for a human check (its quote cannot be read offline)
        self.assertEqual(self.levels(self.check([url])), ["WARN"])
        self.assertEqual(self.levels(self.check([memory])), ["ERROR"])

    def test_a_figure_needs_a_saved_source(self):
        quote = "Alpha sells mining trucks to Rio Tinto, 12% of sales."
        url = row("Alpha", "Rio Tinto", "supplies", "mining trucks", source="https://example.com/10-K",
                  quote=quote, figure="12% of sales")
        found = self.check([url])
        self.assertEqual(sorted(self.levels(found)), ["ERROR", "WARN"])
        self.assertIn("must cite a saved file", " ".join(m for _, m in found))

    def test_scope_spelling_contractors_dates_and_figures(self):
        found = self.check([
            row("Alpha", "Rio Tinto", "supplies", "trucks", scope="ai"),
            row("Alpha", "BETA", "supplies", "office HVAC"),                 # node spelled differently
            row("Alpha", "Marketech", "customer_of", "cleanroom build-out"),  # rule B fab contractor
            row("Alpha", "Rio Tinto", "supplies", "trucks", date="2026-02-15"),
            row("Alpha", "Rio Tinto", "supplies", "trucks", figure="12% of sales"),
        ])
        text = " ".join(message for _, message in found)
        self.assertIn("scope 'ai' must be", text)
        self.assertIn("spelled differently", text)
        self.assertIn("rule B", text)
        self.assertIn("!= `date`", text)
        self.assertIn("figure number '12'", text)

    def test_existing_ai_edge_is_flagged(self):
        found = self.check([row("Alpha", "Beta", "supplies", "office HVAC")])
        self.assertEqual(self.levels(found), ["WARN"])

    def test_committed_rows_may_not_disappear_or_change(self):
        kept = row("Alpha", "Rio Tinto", "supplies", "mining trucks")
        baseline = {"company": "Alpha", "relations": [kept, row("Alpha", "Rio Tinto", "supplies", "haul trucks")]}
        found = self.check([kept], baseline)
        self.assertEqual(self.levels(found), ["ERROR"])
        self.assertIn("ADD-only", found[0][1])
        self.assertEqual(self.check([kept, row("Alpha", "Rio Tinto", "supplies", "haul trucks"),
                                     row("Alpha", "Rio Tinto", "supplies", "spare parts")], baseline), [])


if __name__ == "__main__":
    unittest.main()
