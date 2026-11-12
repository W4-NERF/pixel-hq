"""Class selection and box-shadow sprite behavior in the offline Node harness."""
import json

import pytest

from pixelhq import config
from tests.test_review_ui import run_ui
from tests.test_scoring_collect import collector

VARIANTS = ["default", "wizard", "knight", "engineer", "scout", "medic", "scribe", "rogue"]
# Spec D6: tokens split on [^a-z0-9]+; prefix keywords match a token prefix, exact keywords must equal a token.
PREFIXES = {
    "knight": "secur defen audit guard warden blueteam".split(),
    "rogue": "redteam pentest offens attack".split(),
    "scout": "network netadmin netops firewall rout ranger".split(),
    "engineer": "devops deploy docker build infra sysadmin linux smith platform kube".split(),
    "wizard": "develop code coding program mage".split(),
    "scribe": "data sql docs document writ research librar scribe dbadmin".split(),
    "medic": "help support desk medic".split(),
}
EXACT = {
    "knight": "soc blue".split(), "rogue": ["red"], "scout": "net vpn".split(),
    "engineer": "ops ci cd sre k8s".split(), "wizard": ["dev"], "scribe": "db doc".split(), "medic": [],
}
KEYWORDS = {variant: PREFIXES[variant] + EXACT[variant] for variant in PREFIXES}


def hash_variant(identifier):
    """Independent re-implementation of the id-hash fallback (31-multiplier, uint32, eight variants)."""
    value = 0
    for unit in identifier:  # test ids are ASCII, so code points equal UTF-16 units
        value = (value * 31 + ord(unit)) & 0xFFFFFFFF
    return VARIANTS[value % len(VARIANTS)]


@pytest.mark.parametrize("variant", VARIANTS)
def test_explicit_sprite_wins_over_every_role_keyword(tmp_path, variant):
    run_ui(tmp_path, """
const bot=Object.freeze({id:'security-devops',cls:'red network',title:'medic',sprite:VARIANT});
assert.equal(spriteVariant(bot),VARIANT);
assert.equal(module.exports.spriteVariant,spriteVariant);
""".replace("VARIANT", json.dumps(variant)))


@pytest.mark.parametrize("field", ["cls", "title", "id"])
@pytest.mark.parametrize("variant,keywords", KEYWORDS.items())
def test_each_keyword_group_in_each_roster_field(tmp_path, field, variant, keywords):
    cases = [{"id": "unit", "cls": "", "title": "", field: f"Mixed {word.upper()} role"} for word in keywords]
    run_ui(tmp_path, """
for(const bot of CASES)assert.equal(spriteVariant(bot),EXPECTED,JSON.stringify(bot));
""".replace("CASES", json.dumps(cases)).replace("EXPECTED", json.dumps(variant)))


def test_keyword_order_including_devops_and_invalid_explicit_sprite(tmp_path):
    cases = [({"id": "devops"}, "engineer")]
    ordered = list(KEYWORDS)
    for index, variant in enumerate(ordered):
        cases.append(({"id": "unit", "cls": " ".join(KEYWORDS[name][0] for name in ordered[index:]),
                       "sprite": "not-a-variant"}, variant))
    run_ui(tmp_path, """
for(const [bot,expected] of CASES)assert.equal(spriteVariant(bot),expected);
""".replace("CASES", json.dumps(cases)))


def test_hash_is_stable_across_processes_reordering_and_unrelated_fields(tmp_path):
    probe = """
const ids=Array.from({length:32},(_,i)=>'unit-'+i), choices=ids.map(id=>spriteVariant({id}));
assert.ok(choices.every(choice=>VARIANTS.includes(choice)));
assert.equal(new Set(choices).size,8);
assert.deepEqual(ids.slice().reverse().map(id=>spriteVariant({id})).reverse(),choices);
assert.deepEqual(ids.map(id=>spriteVariant({id,cls:'Recruit',title:'Recruit',zone:'crew',color:'invalid'})),choices);
for(const invalid of [null,[],{},4,'WIZARD','__proto__','constructor'])
  assert.deepEqual(ids.map(id=>spriteVariant({id,sprite:invalid})),choices);
console.log(JSON.stringify(choices));
""".replace("VARIANTS", json.dumps(VARIANTS))
    assert run_ui(tmp_path, probe) == run_ui(tmp_path, probe)


@pytest.mark.parametrize("px", [1, 3, 7])
def test_eight_headgear_shapes_share_body_and_keep_eyes_and_crown(tmp_path, px):
    run_ui(tmp_path, r"""
const px=PX, bot={id:'unit',color:'#5B7A99',zone:'crew'};
const pixels=html=>[...html.matchAll(/(\d+)px (\d+)px 0 (#[\da-fA-F]{6}|rgba\([^)]*\))/g)]
  .map(m=>({x:Number(m[1])/px,y:Number(m[2])/px,color:m[3]}));
const sprites=VARIANTS.map(variant=>sprite({...bot,sprite:variant},px));
assert.equal(new Set(sprites).size,8,'headgear must change the rendered pixels');
const base=pixels(sprites[0]);
for(const [index,html] of sprites.entries()){
  assert.ok(html.includes('width:'+8*px+'px;height:'+9*px+'px'));
  const drawn=pixels(html);
  assert.ok(drawn.every(p=>p.x>=0&&p.x<8&&p.y>=0&&p.y<9));
  assert.deepEqual(drawn.filter(p=>p.y>=4),base.filter(p=>p.y>=4));
  const face=drawn.filter(p=>p.y===3), original=base.filter(p=>p.y===3);
  assert.equal(face.length,original.length);
  assert.ok(face.filter((p,i)=>JSON.stringify(p)!==JSON.stringify(original[i])).length<=2);
  assert.deepEqual(face.filter(p=>p.x===2||p.x===5),original.filter(p=>p.x===2||p.x===5));
  assert.equal(sprite({...bot,sprite:VARIANTS[index],leader:true},px),sprite({...bot,sprite:'default',leader:true},px));
}
DATA.cfg.rooms=[{zones:[{id:'isolation',quarantine:true}]}];
for(const variant of VARIANTS)for(const leader of [false,true]){
  const drawn=pixels(sprite({...bot,sprite:variant,leader,zone:'isolation'},px));
  const eyes=drawn.filter(p=>p.y===(leader?4:3)&&(p.x===2||p.x===5));
  assert.equal(eyes.length,2); assert.ok(eyes.every(p=>p.color==='#C9A23F'));
}
""".replace("PX", str(px)).replace("VARIANTS", json.dumps(VARIANTS)))


@pytest.mark.parametrize("variant", VARIANTS)
def test_roster_sprite_survives_config_and_snapshot(fleet, monkeypatch, variant):
    module = collector(fleet, monkeypatch)
    path = config.roster_path()
    roster = json.loads(path.read_text(encoding="utf-8"))
    roster["bots"][0]["sprite"] = variant
    path.write_text(json.dumps(roster), encoding="utf-8")
    assert config.load_roster()["bots"][0]["sprite"] == variant
    assert module.collect()["bots"][0]["sprite"] == variant


@pytest.mark.parametrize("invalid", ["auto", "WIZARD", "unknown", "", None, 7, True, [], {}])
def test_invalid_roster_sprite_is_dropped_with_bounded_warning(fleet, invalid):
    path = config.roster_path()
    roster = json.loads(path.read_text(encoding="utf-8"))
    roster["bots"][0]["sprite"] = invalid
    path.write_text(json.dumps(roster), encoding="utf-8")
    loaded = config.load_roster()
    assert loaded["rosterSource"] == "file"
    assert "sprite" not in loaded["bots"][0]
    assert len(loaded["bots"]) == len(roster["bots"])
    assert any("bots[0].sprite" in warning for warning in loaded["warnings"])
    assert all(len(warning) <= 120 for warning in loaded["warnings"])
    assert json.loads(path.read_text(encoding="utf-8")) == roster


def test_demo_shows_at_least_five_distinct_nonleader_sprites(tmp_path):
    run_ui(tmp_path, """
const bots=DATA.bots.filter(bot=>!bot.leader);
assert.ok(new Set(bots.map(spriteVariant)).size>=5);
assert.ok(new Set(bots.map(bot=>sprite(bot,3))).size>=5);
""")


@pytest.mark.parametrize("field", ["cls", "title", "id"])
@pytest.mark.parametrize("variant", PREFIXES)
def test_prefix_keywords_match_longer_tokens(tmp_path, field, variant):
    cases = [{"id": "unit", "cls": "", "title": "", field: f"Mixed {word}xyz-role"} for word in PREFIXES[variant]]
    run_ui(tmp_path, """
for(const bot of CASES)assert.equal(spriteVariant(bot),EXPECTED,JSON.stringify(bot));
""".replace("CASES", json.dumps(cases)).replace("EXPECTED", json.dumps(variant)))


@pytest.mark.parametrize("variant", [name for name in EXACT if EXACT[name]])
def test_exact_keywords_never_match_inside_or_at_the_start_of_a_longer_token(tmp_path, variant):
    run_ui(tmp_path, """
const id=Array.from({length:16},(_,i)=>'unit-'+i).find(id=>spriteVariant({id})!==VARIANT);
const fallback=spriteVariant({id});
for(const word of WORDS)for(const text of [word+'xyz','xyz'+word,'x'+word+'x'])
  assert.equal(spriteVariant({id,cls:text,title:''}),fallback,text);
for(const word of WORDS)assert.equal(spriteVariant({id,cls:'  '+word.toUpperCase()+'/x ',title:''}),VARIANT,word);
""".replace("WORDS", json.dumps(EXACT[variant])).replace("VARIANT", json.dumps(variant)))


@pytest.mark.parametrize("field", ["cls", "title", "id"])
@pytest.mark.parametrize("text,expected", [
    ("Shared credentials", None), ("Kubernetes notes", "engineer"), ("devops", "engineer"),
    ("CI/CD, Reverse Proxy", "engineer"), ("Network / Firewall", "scout"), ("SOC, Audits", "knight"),
    ("dev-a", "wizard"),
])
def test_spec_must_hold_cases(tmp_path, field, text, expected):
    bot = {"id": "unit", "cls": "", "title": "", field: text}
    if expected is None:
        expected = hash_variant(bot["id"])
        assert expected != "rogue", "pick a case where a substring match on 'red' would be visible"
    run_ui(tmp_path, "assert.equal(spriteVariant(%s),%s);" % (json.dumps(bot), json.dumps(expected)))
