#!/usr/bin/env python3
"""
Performance benchmarks comparing linear JSON search vs SQLite FTS search.

This script generates test conversations, runs both search methods,
and provides detailed performance comparisons.
"""

import argparse
import asyncio
import json
import logging
import random  # nosec B311 - Used for test data generation, not security purposes
import statistics
import string
import time
from pathlib import Path
from typing import Any

from conversation_memory import ConversationMemoryServer


class SearchBenchmark:
    """Benchmark search performance between linear and SQLite methods."""

    def __init__(self, storage_path: str = "~/claude-memory-benchmark"):
        """Initialize benchmark with test storage path."""
        self.storage_path = Path(storage_path).expanduser()
        self.logger = logging.getLogger(__name__)

        # Clean up any existing benchmark data
        if self.storage_path.exists():
            import shutil

            shutil.rmtree(self.storage_path)

        # Initialize memory servers
        self.linear_server = ConversationMemoryServer(
            storage_path=str(self.storage_path / "linear"), enable_sqlite=False
        )

        self.sqlite_server = ConversationMemoryServer(
            storage_path=str(self.storage_path / "sqlite"), enable_sqlite=True
        )

    def generate_test_data(self, num_conversations: int = 100) -> list[dict[str, Any]]:
        """Generate test conversations with realistic content."""
        self.logger.info(f"Generating {num_conversations} test conversations...")

        # Common programming topics and terms
        tech_terms = [
            "python",
            "javascript",
            "react",
            "django",
            "api",
            "database",
            "sql",
            "authentication",
            "frontend",
            "backend",
            "testing",
            "deployment",
            "docker",
            "kubernetes",
            "aws",
            "performance",
            "optimization",
            "machine learning",
            "data science",
            "algorithms",
            "debugging",
        ]

        conversations = []

        for i in range(num_conversations):
            # Generate realistic conversation content
            num_topics = random.randint(2, 5)  # nosec B311 - Test data generation only
            selected_topics = random.sample(tech_terms, num_topics)  # nosec B311 - Test data generation only

            # Create conversation content with topics
            content_parts = []
            content_parts.append(f"Discussion about {' and '.join(selected_topics[:2])}")

            # Add some random content
            for topic in selected_topics:
                sentence_templates = [
                    f"Working with {topic} has been challenging because",
                    f"The best practices for {topic} include",
                    f"I'm trying to understand how {topic} works with",
                    f"Can you help me debug this {topic} issue where",
                    f"The documentation for {topic} mentions that",
                ]

                template = random.choice(sentence_templates)  # nosec B311 - Test data generation only
                random_detail = "".join(random.choices(string.ascii_lowercase + " ", k=50))  # nosec B311 - Test data generation only
                content_parts.append(f"{template} {random_detail}")

            content = ". ".join(content_parts)
            title = f"Conversation {i + 1}: {selected_topics[0]} discussion"

            conversations.append({"title": title, "content": content, "topics": selected_topics})

        return conversations

    async def populate_test_data(self, conversations: list[dict[str, Any]]):
        """Add test conversations to both storage systems."""
        self.logger.info("Populating test data in both storage systems...")

        for conv in conversations:
            # Add to linear search system
            await self.linear_server.add_conversation(content=conv["content"], title=conv["title"])

            # Add to SQLite search system
            await self.sqlite_server.add_conversation(content=conv["content"], title=conv["title"])

    async def run_search_benchmark(self, query: str, iterations: int = 10) -> dict[str, Any]:
        """Run search benchmark for a specific query."""
        linear_times = []
        sqlite_times = []

        # Benchmark linear search
        for _ in range(iterations):
            start_time = time.perf_counter()
            linear_results = await self.linear_server.search_conversations(query, limit=10)
            end_time = time.perf_counter()
            linear_times.append((end_time - start_time) * 1000)  # Convert to milliseconds

        # Benchmark SQLite search
        for _ in range(iterations):
            start_time = time.perf_counter()
            sqlite_results = await self.sqlite_server.search_conversations(query, limit=10)
            end_time = time.perf_counter()
            sqlite_times.append((end_time - start_time) * 1000)  # Convert to milliseconds

        # Calculate statistics
        linear_stats = {
            "mean": statistics.mean(linear_times),
            "median": statistics.median(linear_times),
            "stdev": statistics.stdev(linear_times) if len(linear_times) > 1 else 0,
            "min": min(linear_times),
            "max": max(linear_times),
        }

        sqlite_stats = {
            "mean": statistics.mean(sqlite_times),
            "median": statistics.median(sqlite_times),
            "stdev": statistics.stdev(sqlite_times) if len(sqlite_times) > 1 else 0,
            "min": min(sqlite_times),
            "max": max(sqlite_times),
        }

        # Calculate performance improvement
        speedup = linear_stats["mean"] / sqlite_stats["mean"] if sqlite_stats["mean"] > 0 else 0

        return {
            "query": query,
            "iterations": iterations,
            "linear_search": {
                "times_ms": linear_times,
                "stats": linear_stats,
                "result_count": (len(linear_results) if isinstance(linear_results, list) else 0),
            },
            "sqlite_search": {
                "times_ms": sqlite_times,
                "stats": sqlite_stats,
                "result_count": (len(sqlite_results) if isinstance(sqlite_results, list) else 0),
            },
            "performance": {
                "speedup_factor": speedup,
                "time_saved_ms": linear_stats["mean"] - sqlite_stats["mean"],
                "percentage_improvement": (
                    ((linear_stats["mean"] - sqlite_stats["mean"]) / linear_stats["mean"] * 100)
                    if linear_stats["mean"] > 0
                    else 0
                ),
            },
        }

    async def run_comprehensive_benchmark(self, num_conversations: int = 100) -> dict[str, Any]:
        """Run comprehensive benchmark with various queries."""
        self.logger.info(
            f"Running comprehensive benchmark with {num_conversations} conversations..."
        )

        # Generate and populate test data
        conversations = self.generate_test_data(num_conversations)
        await self.populate_test_data(conversations)

        # Test queries of varying complexity
        test_queries = [
            "python",
            "javascript react",
            "database authentication",
            "performance optimization docker",
            "machine learning data science algorithms",
        ]

        benchmark_results: dict[str, Any] = {
            "setup": {
                "num_conversations": num_conversations,
                "storage_path": str(self.storage_path),
                "timestamp": time.time(),
            },
            "queries": [],
        }

        for query in test_queries:
            self.logger.info(f"Benchmarking query: '{query}'")
            result = await self.run_search_benchmark(query, iterations=5)
            benchmark_results["queries"].append(result)

        # Calculate overall statistics
        all_linear_times: list[float] = []
        all_sqlite_times: list[float] = []

        for query_result in benchmark_results["queries"]:
            all_linear_times.extend(query_result["linear_search"]["times_ms"])
            all_sqlite_times.extend(query_result["sqlite_search"]["times_ms"])

        overall_linear_mean = statistics.mean(all_linear_times)
        overall_sqlite_mean = statistics.mean(all_sqlite_times)

        benchmark_results["overall"] = {
            "linear_mean_ms": overall_linear_mean,
            "sqlite_mean_ms": overall_sqlite_mean,
            "overall_speedup": (
                overall_linear_mean / overall_sqlite_mean if overall_sqlite_mean > 0 else 0
            ),
            "overall_improvement_percent": (
                ((overall_linear_mean - overall_sqlite_mean) / overall_linear_mean * 100)
                if overall_linear_mean > 0
                else 0
            ),
        }

        return benchmark_results

    def print_benchmark_report(self, results: dict[str, Any]):
        """Print a formatted benchmark report."""
        print(f"\n{'=' * 60}")
        print("SEARCH PERFORMANCE BENCHMARK REPORT")
        print(f"{'=' * 60}")
        print("Test Setup:")
        print(f"  • Conversations: {results['setup']['num_conversations']}")
        print(f"  • Storage Path: {results['setup']['storage_path']}")
        print(f"  • Timestamp: {time.ctime(results['setup']['timestamp'])}")

        print(f"\n{'Query Results:'}")
        print(f"{'─' * 60}")

        for query_result in results["queries"]:
            query = query_result["query"]
            linear = query_result["linear_search"]["stats"]
            sqlite = query_result["sqlite_search"]["stats"]
            perf = query_result["performance"]

            print(f"\nQuery: '{query}'")
            print(f"  Linear Search:  {linear['mean']:.2f}ms (±{linear['stdev']:.2f}ms)")
            print(f"  SQLite Search:  {sqlite['mean']:.2f}ms (±{sqlite['stdev']:.2f}ms)")
            print(f"  Speedup:        {perf['speedup_factor']:.1f}x faster")
            print(f"  Improvement:    {perf['percentage_improvement']:.1f}%")

        print(f"\n{'Overall Performance:'}")
        print(f"{'─' * 60}")
        overall = results["overall"]
        print(f"  Average Linear:   {overall['linear_mean_ms']:.2f}ms")
        print(f"  Average SQLite:   {overall['sqlite_mean_ms']:.2f}ms")
        print(f"  Overall Speedup:  {overall['overall_speedup']:.1f}x faster")
        print(f"  Overall Improvement: {overall['overall_improvement_percent']:.1f}%")

        print(f"\n{'Conclusion:'}")
        print(f"{'─' * 60}")
        if overall["overall_speedup"] > 1:
            print(f"  ✅ SQLite FTS is {overall['overall_speedup']:.1f}x faster than linear search")
            print(f"  ✅ Performance improvement of {overall['overall_improvement_percent']:.1f}%")
        else:
            print("  ⚠️  Linear search performed better in this test")

        print(f"\n{'=' * 60}")

    def cleanup(self):
        """Clean up benchmark data."""
        if self.storage_path.exists():
            import shutil

            shutil.rmtree(self.storage_path)


async def main():
    """Main benchmark execution."""
    parser = argparse.ArgumentParser(description="Benchmark search performance")
    parser.add_argument(
        "--conversations",
        type=int,
        default=100,
        help="Number of test conversations to generate (default: 100)",
    )
    parser.add_argument(
        "--storage-path",
        default="~/claude-memory-benchmark",
        help="Path for benchmark storage (default: ~/claude-memory-benchmark)",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--output-json", help="Save results to JSON file")

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    benchmark = SearchBenchmark(args.storage_path)

    try:
        # Run benchmark
        results = await benchmark.run_comprehensive_benchmark(args.conversations)

        # Print report
        benchmark.print_benchmark_report(results)

        # Save to JSON if requested
        if args.output_json:
            output_file = Path(args.output_json)

            # Helper function for async-safe file I/O
            def write_json():
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(results, f, indent=2)

            # Use asyncio.to_thread for async-safe file I/O
            await asyncio.to_thread(write_json)
            print(f"\nResults saved to: {output_file}")

    finally:
        # Clean up
        benchmark.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
