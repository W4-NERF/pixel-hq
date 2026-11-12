"""Reactor metrics: non-finite samples, an idle cache and an unreachable Prometheus never break the snapshot."""
import json
import urllib.error

import pytest

from pixelhq import collect, config


@pytest.fixture
def cfg():
    settings = config.load()
    settings.update(prometheus_url="https://metrics.example", model_endpoint="", metrics_prefix="sample")
    return settings


def _vector(value, instance=None):
    return {"data": {"result": [{"metric": {"instance": instance} if instance else {}, "value": [0, value]}]}}


@pytest.mark.parametrize("value", ["NaN", "+Inf", "-Inf", "not-a-number", None])
def test_non_finite_or_malformed_samples_become_unknown_and_the_snapshot_stays_json(cfg, monkeypatch, value):
    monkeypatch.setattr(collect, "http_json", lambda url: _vector(value, "node-1"))
    reactor = collect.read_reactor(cfg)
    assert reactor["nodes"] == [] and reactor["srv"] is None
    json.dumps(reactor, allow_nan=False)  # what the HTTP response encoder requires


def test_finite_samples_next_to_nan_ones_are_kept(cfg, monkeypatch):
    def http_json(url):
        if "DCGM_FI_DEV_GPU_UTIL" in url:
            return _vector("NaN", "node-1")
        if "DCGM_FI_DEV_POWER_USAGE" in url:
            return _vector("231.6", "node-1")
        return _vector("NaN") if "time_to_first_token" in url else _vector("2")
    monkeypatch.setattr(collect, "http_json", http_json)
    reactor = collect.read_reactor(cfg)
    assert reactor["nodes"] == [{"id": "node-1", "power": 232}]
    assert reactor["srv"]["ttftP50"] is None and reactor["srv"]["running"] == 2.0
    json.dumps(reactor, allow_nan=False)


def test_an_idle_kv_cache_reading_of_zero_is_kept(cfg, monkeypatch):
    def http_json(url):
        if "kv_cache_usage_ratio" in url:
            return {"data": {"result": []}}
        if "kv_cache_usage_perc" in url:
            return _vector("0")
        if "gpu_cache_usage_perc" in url:
            raise AssertionError("0.0 is a reading, not a missing value")
        return {"data": {"result": []}}
    monkeypatch.setattr(collect, "http_json", http_json)
    assert collect.read_reactor(cfg)["srv"]["kv"] == 0.0


def test_an_unreachable_prometheus_is_asked_once_per_snapshot(cfg, monkeypatch):
    calls = []
    def unreachable(url):
        calls.append(url)
        raise urllib.error.URLError("Sample connection refused")
    monkeypatch.setattr(collect, "http_json", unreachable)
    reactor = collect.read_reactor(cfg)
    assert len(calls) == 1
    assert reactor == {"nodes": [], "model": None, "engine": "sample", "srv": None}


def test_a_failing_query_does_not_stop_the_other_queries(cfg, monkeypatch):
    calls = []
    def http_json(url):
        calls.append(url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(url, 400, "Sample bad query", None, None)
        return _vector("3")
    monkeypatch.setattr(collect, "http_json", http_json)
    reactor = collect.read_reactor(cfg)
    assert len(calls) > 2 and reactor["srv"]["running"] == 3.0
