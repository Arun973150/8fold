"""Source adapters. Each adapter reads ONE source type and emits
``SourceRecord`` objects keyed by canonical field names. Adapters do not
normalize and do not merge -- they only read and tag. Mapping a source's own
vocabulary onto ours (notably the ATS blob) happens here.
"""
