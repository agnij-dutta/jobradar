"""Stack vocabulary and description scoring.

Every term is a regex so that "Go" the language does not match "go to market"
and "TS" does not match every sentence that ends in "ts".
"""

from __future__ import annotations

import re

# term -> pattern. Case-insensitive unless the pattern starts with (?-i).
VOCAB: dict[str, str] = {
    "typescript": r"\btypescript\b|\bTS\b(?=[,/ ]+(?:node|react|javascript|js))",
    "javascript": r"\bjavascript\b|\bES20\d\d\b",
    "node": r"\bnode(?:\.?js)?\b(?!\s+(?:operator|runner))|\bnestjs\b|\bexpress\.?js\b",
    "react": r"\breact(?:\.?js)?\b(?![- ]native)",
    "react-native": r"\breact[- ]native\b",
    "nextjs": r"\bnext\.?js\b",
    "vue": r"\bvue(?:\.?js)?\b",
    "python": r"\bpython\b",
    "go": r"\bgolang\b|(?-i:\bGo\b)(?!\s+(?:to|live|deep|beyond|above|after|fast|back|through|from|out|on|in|with|-to))",
    "rust": r"\brust\b",
    "java": r"\bjava\b(?!script)",
    "kotlin": r"\bkotlin\b",
    "scala": r"\bscala\b",
    "c++": r"\bc\+\+|\bcpp\b",
    "c#": r"\bc#|\.net\b",
    "swift": r"(?-i:\bSwift\b)",
    "ruby": r"\bruby\b|\brails\b",
    "elixir": r"\belixir\b|\berlang\b",
    "php": r"\bphp\b|\blaravel\b",
    "solidity": r"\bsolidity\b",
    "vyper": r"\bvyper\b",
    "evm": r"\bevm\b|\bethereum virtual machine\b",
    "ethereum": r"\bethereum\b",
    "solana": r"\bsolana\b",
    "anchor": r"(?-i:\bAnchor\b)",
    "move": r"(?-i:\bMove\b)(?= (?:language|smart|contracts?|VM))|\bsui move\b|\baptos move\b",
    "cairo": r"\bcairo\b",
    "zk": r"\bzero[- ]knowledge\b|\bzk[- ]?(?:snarks?|starks?|proofs?|vm|evm|rollups?)?\b|\bplonk\b|\bhalo2\b|\bcircom\b",
    "foundry": r"\bfoundry\b|\bforge test\b",
    "hardhat": r"\bhardhat\b",
    "viem": r"\bviem\b|\bwagmi\b|\bethers(?:\.js)?\b",
    "defi": r"\bdefi\b|\bdecentralized finance\b",
    "stablecoin": r"\bstablecoins?\b|\busdc\b|\busdt\b",
    "wallet": r"\bwallets?\b",
    "smart-contracts": r"\bsmart contracts?\b",
    "bitcoin": r"\bbitcoin\b|\blightning network\b",
    "payments": r"\bpayments?\b|\bpayment rails\b|\bcard issuing\b",
    "postgres": r"\bpostgres(?:ql)?\b",
    "mysql": r"\bmysql\b",
    "mongodb": r"\bmongo(?:db)?\b",
    "redis": r"\bredis\b",
    "kafka": r"\bkafka\b",
    "graphql": r"\bgraphql\b",
    "grpc": r"\bgrpc\b|\bprotobuf\b",
    "sql": r"\bsql\b",
    "kubernetes": r"\bkubernetes\b|\bk8s\b",
    "docker": r"\bdocker\b|\bcontainers?\b",
    "terraform": r"\bterraform\b",
    "aws": r"\baws\b|\bamazon web services\b",
    "gcp": r"\bgcp\b|\bgoogle cloud\b",
    "azure": r"\bazure\b",
    "llm": r"\bllms?\b|\blarge language models?\b|\bgpt-?\d?\b|\bclaude\b",
    "ai-agents": r"\bai agents?\b|\bagentic\b|\bagents? framework\b",
    "ml": r"\bmachine learning\b|\bml\b|\bdeep learning\b",
    "pytorch": r"\bpytorch\b",
    "rag": r"\brag\b|\bretrieval[- ]augmented\b",
    "spark": r"\bspark\b(?! of)",
    "airflow": r"\bairflow\b",
    "dbt": r"\bdbt\b",
    "ios": r"\bios\b",
    "android": r"\bandroid\b",
    "distributed-systems": r"\bdistributed systems?\b",
    "microservices": r"\bmicroservices?\b",
}

ALIASES = {
    "ts": "typescript",
    "js": "javascript",
    "nodejs": "node",
    "node.js": "node",
    "golang": "go",
    "postgresql": "postgres",
    "pg": "postgres",
    "k8s": "kubernetes",
    "next": "nextjs",
    "next.js": "nextjs",
    "reactjs": "react",
    "sol": "solidity",
    "zero-knowledge": "zk",
    "ethers": "viem",
    "wagmi": "viem",
    "ai": "llm",
    "agents": "ai-agents",
    "smart contracts": "smart-contracts",
    "smart-contract": "smart-contracts",
    "rn": "react-native",
    "cpp": "c++",
    "dotnet": "c#",
    "stablecoins": "stablecoin",
    "web3": "ethereum",
}

_COMPILED = {k: re.compile(v, re.I) for k, v in VOCAB.items()}


def resolve_term(term: str) -> tuple[str, re.Pattern]:
    """Resolve a user term (with aliases) to a vocabulary name and regex; unknown terms match as whole words."""
    t = term.strip().lower()
    t = ALIASES.get(t, t)
    if t in _COMPILED:
        return t, _COMPILED[t]
    return t, re.compile(r"\b" + re.escape(t) + r"\b", re.I)


def tag_counts(title: str, text: str) -> dict[str, int]:
    """Counts of each vocab term in title+description (title weighted x3)."""
    out: dict[str, int] = {}
    for k, rx in _COMPILED.items():
        n = len(rx.findall(text or "")) + 3 * len(rx.findall(title or ""))
        if n:
            out[k] = min(n, 20)
    return out


def score(title: str, text: str, terms: list[str]) -> tuple[float, list[str], list[str]]:
    """Returns (score 0..100, matched explanations, missing terms)."""
    if not terms:
        return 0.0, [], []
    total = 0.0
    matched: list[str] = []
    missing: list[str] = []
    for raw in terms:
        name, rx = resolve_term(raw)
        in_title = len(rx.findall(title or ""))
        in_desc = len(rx.findall(text or ""))
        if not in_title and not in_desc:
            missing.append(name)
            continue
        s = 0.6 + min(in_desc, 5) * 0.06 + (0.3 if in_title else 0.0)
        total += min(s, 1.0)
        bits = []
        if in_title:
            bits.append("in title")
        if in_desc:
            bits.append(f"{in_desc}x in description")
        matched.append(f"{name} ({', '.join(bits)})")
    return round(100 * total / len(terms), 1), matched, missing
