import sys
import os

# Ensure the parent directory is in the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from veda.retrieval import embeddings

def run_oil_benchmark():
    print("Running Synthetic OIL-like Construction Activity Benchmark...")
    
    # Synthetic OIL (Oil & Gas / Heavy Construction) activities
    activities = [
        "Hydrotesting of pipe spool ISO-1234 on Level 2",
        "Erection of structural steel frame for main compressor building",
        "Pre-fabrication of stainless steel piping spools",
        "Pulling 1500m of low voltage electrical cables in Trench A",
        "Grouting of main water injection pump foundation",
        "Scaffolding setup for column 10-A inspection",
        "Insulation and cladding of separator vessel V-200",
        "Alignment and bolting of flanged connection on 24-inch crude line",
        "NDT (Non-Destructive Testing) of welded joints on pipeline segment 3",
        "Installation of HVAC ducts in Control Room"
    ]
    
    # Create the retriever based on current config
    backend_name = os.environ.get("VEDA_EMBEDDING_BACKEND", "hash")
    print(f"Initializing {backend_name} backend...")
    
    backend = embeddings.get_backend()
    
    print("Encoding synthetic activities...")
    doc_embs = backend.encode(activities)
        
    # Run some domain-specific queries
    queries = [
        "pipe spool testing",
        "cable pulling",
        "pump foundation work",
        "welding inspection"
    ]
    
    passed = 0
    total = len(queries)
    
    for q in queries:
        print(f"\nQuery: '{q}'")
        q_emb = backend.encode([q])[0]
        
        # Calculate cosine similarity
        scores = []
        for i, doc_emb in enumerate(doc_embs):
            score = embeddings.cosine(q_emb, doc_emb)
            scores.append((score, i))
            
        scores.sort(key=lambda x: x[0], reverse=True)
        
        print("Top results:")
        for score, idx in scores[:2]:
            print(f" - {score:.3f} : {activities[idx]}")
            
        # Basic check: do we get the right document as top 1?
        top_idx = scores[0][1] if scores else -1
        if q == "pipe spool testing" and top_idx == 0: passed += 1
        elif q == "cable pulling" and top_idx == 3: passed += 1
        elif q == "pump foundation work" and top_idx == 4: passed += 1
        elif q == "welding inspection" and top_idx == 8: passed += 1
        else:
            print(f"  [!] Query '{q}' didn't return the expected top result.")
            
    print(f"\nBenchmark completed. {passed}/{total} queries matched perfectly.")
    return passed == total

if __name__ == "__main__":
    success = run_oil_benchmark()
    sys.exit(0 if success else 1)
