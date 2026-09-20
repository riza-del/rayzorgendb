# RayzorgenDB

High-performance embedded database engine built for native execution.

RayzorgenDB delivers a complete storage and query engine within a unified package, combining multiple data models and advanced capabilities into a streamlined, self-contained architecture.

Supported Python versions: 3.8 and newer.

## Overview

Designed for maximum efficiency and portability, RayzorgenDB integrates advanced indexing, custom binary storage, and a robust query layer natively. It eliminates infrastructure overhead, enabling seamless local integration for modern applications.

## Feature Summary

### Storage Engine
- Custom binary format with varint encoding
- Write-Ahead Log with automatic crash recovery
- zlib compression (delivering approximately 82 percent size reduction)
- CRC32 checksum verification
- Paged disk storage supporting datasets exceeding available RAM
- Atomic write operations with configurable fsync policies

### Query Layer
- Native hand-written SQL parser (approximately 1,400 lines)
- Chainable Python query builder interface
- Cost-based query optimizer utilizing statistical analysis
- EXPLAIN and ANALYZE tools for query execution planning
- Full-text search capabilities across all fields
- Advanced aggregations: SUM, AVG, MIN, MAX, and COUNT
- Comprehensive support for GROUP BY, HAVING, and DISTINCT clauses

### Indexing
- Hash indexes optimized for exact equality lookups
- B+ Tree indexes designed for efficient range queries
- Prefix search support
- Dynamic index selection handled by the query optimizer
- Bulk loading mechanisms for rapid index reconstruction

### Relational Operations
- Standard INNER, LEFT, and RIGHT JOIN implementations
- Multi-collection join chaining
- Seamless nested field access
- Advanced filtering applied directly to join results
