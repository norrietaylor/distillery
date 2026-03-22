# T14 (T03.1): Define EmbeddingProvider protocol - Proof Summary

## Task Description
Define the EmbeddingProvider protocol in `src/distillery/embedding/protocol.py` with:
- `embed(text: str) -> list[float]` for single text embedding
- `embed_batch(texts: list[str]) -> list[list[float]]` for batch embedding
- `dimensions` property returning vector dimensionality (int)
- `model_name` property returning the model identifier (str)
- Full type hints and docstrings
- Export from `embedding/__init__.py`

## Files Created
- `src/distillery/embedding/protocol.py` - EmbeddingProvider protocol definition
- `src/distillery/embedding/__init__.py` - Module exports
- `src/distillery/__init__.py` - Package initialization
- `src/distillery/store/__init__.py` - Store module initialization

## Proof Artifacts

### T14-01-import-test.txt
**Status**: PASS
**Type**: Test - Protocol Import & Structure Verification
Tests that:
- Protocol can be imported from distillery.embedding
- All required methods exist: embed, embed_batch
- All required properties exist: dimensions, model_name
- Method signatures are correct with proper type hints

### T14-02-type-check.txt
**Status**: PASS
**Type**: Test - Type Checking and Linting
Tests that:
- mypy --strict passes with no errors
- ruff linting passes with no issues
- Code conforms to strict type checking standards

### T14-03-protocol-usage.txt
**Status**: PASS
**Type**: Test - Protocol Structural Typing
Tests that:
- Protocol can be used for structural typing (duck typing)
- Concrete implementations that satisfy the protocol interface work correctly
- Methods return correct types
- Properties work as expected

## Implementation Details

### Protocol Definition
The EmbeddingProvider protocol is defined using Python's `typing.Protocol` to enable structural subtyping. This allows any class that implements the required methods and properties to satisfy the protocol without explicit inheritance.

### Methods
1. **embed(text: str) -> list[float]**
   - Embeds a single text string
   - Returns a list of float values representing the embedding vector
   - Used for embedding individual queries or documents

2. **embed_batch(texts: list[str]) -> list[list[float]]**
   - Embeds multiple texts efficiently in a batch operation
   - Returns a list of embedding vectors, one per input text
   - Allows implementations to use batch APIs for efficiency and cost optimization

### Properties
1. **dimensions: int**
   - Returns the dimensionality of the embedding vectors
   - Allows consumers to understand vector shape and allocate storage/compute resources
   - For Jina v3, default is 1024; for OpenAI text-embedding-3-small, default is 512

2. **model_name: str**
   - Returns the model identifier
   - Used for tracking which embedding model was used in the database
   - Critical for preventing mixed embeddings from different models

## Type Hints
All methods and properties include full type hints:
- Input parameters are typed (str, list[str])
- Return types are explicit (list[float], list[list[float]], int, str)
- Properties are properly decorated with @property
- Enables static type checking with mypy --strict

## Code Quality
- Passes mypy --strict type checking
- Passes ruff linting with zero issues
- Full docstrings on all public methods and properties
- Clear parameter descriptions and return value documentation

## Blocks
This protocol definition unblocks:
- T03.2: Implement JinaEmbeddingProvider (#15)
- T03.3: Implement OpenAIEmbeddingProvider (#16)
- T03: Configurable Embedding Provider (epic #3)

## Verification
All proof artifacts show the protocol:
1. Can be imported and introspected correctly
2. Has all required methods and properties with correct signatures
3. Passes strict type checking and linting standards
4. Enables proper structural typing for embedding implementations
5. Is ready for concrete implementations (Jina, OpenAI, etc.)
