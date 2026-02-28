# CLI: python -m rhokp "your query"
import json
import sys
from .retrieve import retrieve

def main():
    if len(sys.argv) < 2:
        print("Usage: python -m rhokp <query>", file=sys.stderr)
        sys.exit(1)
    query = " ".join(sys.argv[1:])
    result = retrieve(query)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
