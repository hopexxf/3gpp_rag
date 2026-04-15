#!/usr/bin/env python3
"""Read config and output JSON"""
import sys
import json

sys.path.insert(0, 'src')
from config_loader import load_config

c = load_config()

# Use _resolved_paths for log_dir (handles empty fallback)
resolved = c.get('_resolved_paths', {})

print(json.dumps({
    'protocol_base': str(resolved.get('protocol_base', c['paths']['protocol_base'])),
    'embed': str(c['database']['embedding_model_local_path']),
    'rerank': str(c['reranker']['model_local_path']),
    'log_dir': str(resolved.get('log_dir', ''))
}))
