---
tags: [ai, llm, reasoning, cognition, philosophy-of-mind]
date: 2025-04-12
---

# LLMs Are Not Reasoning

There is a persistent category error in how we talk about large language models. When GPT-4 solves a logic puzzle, commentators say it is "reasoning." But what it is actually doing is pattern-matching over a compressed statistical representation of human reasoning traces. These are not the same thing.

Reasoning, in the philosophical sense, requires the maintenance of logical commitments across time. A reasoner must be able to say "I believe X, and X entails Y, therefore I am committed to Y" — and to feel the force of that commitment. LLMs do something that looks like this from the outside, but they have no persistent belief state. Each token is generated fresh from a context window. There is no "therefore" in the model's experience, only a next-token probability that happens to place "therefore" in a high-likelihood position because it appeared in similar contexts during training.

This matters practically, not just philosophically. The failure modes of LLMs — hallucination, logical inconsistency across long contexts, inability to reliably distinguish valid from invalid arguments — all follow directly from the absence of genuine reasoning. If you treat an LLM as a reasoning engine, you will be surprised by these failures. If you treat it as a [[Attention-mechanism-intuition|sophisticated pattern matcher]], they are exactly what you would predict.

The interesting question is whether reasoning can emerge from pattern-matching at sufficient scale. I am skeptical. [[The-hard-problem-is-unsolvable|The hard problem]] suggests that certain qualitative features of cognition may not reduce to computational processes at all, no matter how complex. But even if I am wrong about that, we should be precise about what current systems are doing. Calling it "reasoning" flatters the technology and misleads the user.
