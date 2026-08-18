#!/usr/bin/env python3
"""
Validate and test the memory system after bulk import
"""

import asyncio
import sys
from pathlib import Path

from universal_memory_mcp.conversation_memory import ConversationMemoryServer

# Add the project root to path using dynamic resolution
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


async def validate_memory_system():
    """Run validation tests on the memory system"""

    print("🧪 Memory System Validation")
    print("=" * 40)

    try:
        server = ConversationMemoryServer()

        # Test 1: Search functionality
        print("\n🔍 Test 1: Search functionality")
        print("-" * 30)

        test_queries = ["python", "mcp", "development", "testing"]

        for query in test_queries:
            try:
                results = await server.search_conversations(query, limit=3)
                if results and len(results) > 0:
                    # Check if results contain errors
                    if any("error" in result for result in results):
                        print(
                            f"❌ Search '{query}' failed: {results[0].get('error', 'Unknown error')}"
                        )
                    else:
                        count = len(results)
                        print(f"✅ Search '{query}': {count} results found")

                        # Show first result preview
                        if count > 0:
                            first_result = results[0]
                            title = first_result.get("title", "No title")[:50]
                            print(f"   📄 Top result: {title}...")
                else:
                    print(f"⚠️  Search '{query}': No results found")
            except Exception as e:  # noqa: BLE001 - manual CLI diagnostic script: print/report and continue rather than crash mid-run
                print(f"❌ Search '{query}' failed: {e}")

        # Test 2: Add a test conversation
        print("\n➕ Test 2: Add conversation")
        print("-" * 30)

        test_content = """
# Test Conversation

This is a test conversation to validate the memory system is working.

**Human**: Test question about validation

**Claude**: This is a test response for validation purposes.
        """

        try:
            result = await server.add_conversation(
                test_content, "Memory System Validation Test", "2025-06-01T15:30:00Z"
            )

            if result.get("status") == "success":
                print("✅ Add conversation: Success")
            else:
                print(f"❌ Add conversation failed: {result.get('message', 'Unknown error')}")
        except Exception as e:  # noqa: BLE001 - manual CLI diagnostic script: print/report and continue rather than crash mid-run
            print(f"❌ Add conversation failed: {e}")

        # Test 3: Search for the test conversation
        print("\n🔎 Test 3: Search for test conversation")
        print("-" * 30)

        try:
            results = await server.search_conversations("validation test", limit=1)
            if results and len(results) > 0:
                found_test = any(
                    "validation" in result.get("title", "").lower() for result in results
                )
                if found_test:
                    print("✅ Test conversation found in search")
                else:
                    print("⚠️  Test conversation not found in search results")
            else:
                print("⚠️  No search results for test conversation")
        except Exception as e:  # noqa: BLE001 - manual CLI diagnostic script: print/report and continue rather than crash mid-run
            print(f"❌ Search for test conversation failed: {e}")

        # Test 4: Weekly summary generation
        print("\n📅 Test 4: Weekly summary generation")
        print("-" * 30)

        try:
            summary = await server.generate_weekly_summary()
            if summary and isinstance(summary, str) and len(summary) > 0:
                print("✅ Weekly summary: Generated successfully")
                print(f"   📊 Summary length: {len(summary)} characters")

                # Show first few lines of summary
                lines = summary.split("\n")[:3]
                preview = "\n".join(lines)
                print(f"   📄 Preview: {preview[:100]}...")
            else:
                print("⚠️  Weekly summary: No summary generated")
        except Exception as e:  # noqa: BLE001 - manual CLI diagnostic script: print/report and continue rather than crash mid-run
            print(f"❌ Weekly summary failed: {e}")

        print("\n🎯 Validation Complete")
        print("=" * 40)
        print("💡 If all tests show ✅, your memory system is working correctly!")

    except Exception as e:  # noqa: BLE001 - manual CLI diagnostic script: print/report and continue rather than crash mid-run
        print(f"❌ Critical error during validation: {e}")
        return False

    return True


async def show_system_stats():
    """Show statistics about the imported conversations"""

    print("\n📊 System Statistics")
    print("=" * 40)

    try:
        server = ConversationMemoryServer()

        # Get some overall stats by searching for common terms
        common_terms = [
            "python",
            "mcp",
            "claude",
            "development",
            "code",
            "terraform",
            "azure",
        ]

        total_searches = 0
        total_results = 0

        for term in common_terms:
            try:
                results = await server.search_conversations(term, limit=10)
                if (
                    results
                    and len(results) > 0
                    and not any("error" in result for result in results)
                ):
                    count = len(results)
                    total_results += count
                    print(f"🏷️  '{term}': {count} conversations")
                total_searches += 1
            except Exception:  # noqa: BLE001 - manual CLI diagnostic script: print/report and continue rather than crash mid-run
                pass

        if total_searches > 0:
            avg_results = total_results / total_searches
            print(f"\n📈 Average results per search: {avg_results:.1f}")

        print("\n💾 Memory system is operational and searchable!")

    except Exception as e:  # noqa: BLE001 - manual CLI diagnostic script: print/report and continue rather than crash mid-run
        print(f"❌ Error getting system stats: {e}")


async def main():
    """Main validation routine"""

    # Check if the memory system components exist using dynamic path resolution
    memory_dir = Path(__file__).parent.parent

    required_files = [
        "universal_memory_mcp.server_fastmcp.py",
        "bulk_import_enhanced.py",
    ]

    print("🔧 Checking system components...")
    missing_files = []

    for file in required_files:
        if not (memory_dir / file).exists():
            missing_files.append(file)

    if missing_files:
        print(f"❌ Missing required files: {missing_files}")
        print("💡 Please ensure the memory system is properly installed")
        return False

    print("✅ All required files found")

    # Run validation tests
    success = await validate_memory_system()

    if success:
        await show_system_stats()

    return success


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
