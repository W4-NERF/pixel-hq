/* Pixel sprites (variants, crown, quarantine eyes) and the speech bubble above a bot. */
const SPRITE_VARIANTS = ['default', 'wizard', 'knight', 'engineer', 'scout', 'medic', 'scribe', 'rogue'];

/* [variant, token prefixes, exact tokens]; first variant with any matching token wins (round-2 spec D6) */
const SPRITE_KEYWORDS = [
  ['knight', ['secur', 'defen', 'audit', 'guard', 'warden', 'blueteam'], ['soc', 'blue']],
  ['rogue', ['redteam', 'pentest', 'offens', 'attack'], ['red']],
  ['scout', ['network', 'netadmin', 'netops', 'firewall', 'rout', 'ranger'], ['net', 'vpn']],
  [
    'engineer',
    ['devops', 'deploy', 'docker', 'build', 'infra', 'sysadmin', 'linux', 'smith', 'platform', 'kube'],
    ['ops', 'ci', 'cd', 'sre', 'k8s']
  ],
  ['wizard', ['develop', 'code', 'coding', 'program', 'mage'], ['dev']],
  ['scribe', ['data', 'sql', 'docs', 'document', 'writ', 'research', 'librar', 'scribe', 'dbadmin'], ['db', 'doc']],
  ['medic', ['help', 'support', 'desk', 'medic'], []]
];

function spriteVariant(bot) {
  if (SPRITE_VARIANTS.includes(bot.sprite)) {
    return bot.sprite;
  }
  const tokens = [bot.cls || '', bot.title || '', bot.id || ''].join(' ').toLowerCase().split(/[^a-z0-9]+/).filter(
    Boolean
  );
  const match = SPRITE_KEYWORDS.find(([, prefixes, exact]) =>
    tokens.some((token) => exact.includes(token) || prefixes.some((prefix) => token.startsWith(prefix)))
  );
  if (match) {
    return match[0];
  }
  const id = String(bot.id || '');
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = (Math.imul(hash, 31) + id.charCodeAt(i)) >>> 0;
  }
  return SPRITE_VARIANTS[hash % SPRITE_VARIANTS.length];
}

if (typeof module !== 'undefined') {
  module.exports = { spriteVariant };
}

/* 8×9 pixel sprite drawn with box-shadow; leader gets a crown, quarantine zone gets amber eyes */
const SPR = [
  "..a..a..",
  "..XXXX..",
  ".XXXXXX.",
  ".XeXXeX.",
  ".XXXXXX.",
  "..XmmX..",
  ".XXXXXX.",
  "X.XXXX.X",
  "..X..X.."
];
const HEAD = {
  default: SPR.slice(0, 3),
  wizard: ['...a....', '..XaX...', '.XXXXXa.'],
  knight: ['..aaaa..', '.aaaaaa.', '.ammmma.'],
  engineer: ['..cccc..', '.ccXXcc.', 'cccccccc'],
  scout: ['..XXXX..', '.XXXXXX.', '.XaaaaX.'],
  medic: ['....r...', '..Xrrr..', '.aaaraa.'],
  scribe: ['........', '..aaaa..', '.aaaaaaa'],
  rogue: ['..XmmX..', '.mXXXXm.', '.XXaaXX.']
};
const CROWN = ["c.c..c.c", "cccccccc"];
const quarantineZones = () =>
  new Set(CFG().rooms.flatMap((r) => (r.zones || []).filter((z) => z.quarantine).map((z) => z.id)));

function sprite(b, px) {
  px = px || 4;
  const variant = spriteVariant(b);
  let rows = HEAD[variant].concat([variant === 'rogue' ? '.XemmeX.' : SPR[3]], SPR.slice(4));
  if (b.leader) {
    rows = CROWN.concat(SPR.slice(1));
  }
  if (quarantineZones().has(b.zone)) {
    rows = rows.map((r) => r.replace(/e/g, 'q'));
  }
  const p = palette();
  const colors = { X: safeColor(b.color), e: p.eye, q: p.amber, a: p.accent, m: p.shade, c: p.amber, r: p.rust };
  const sh = [];
  rows.forEach((row, y) =>
    [...row].forEach((c, x) => {
      const m = colors[c];
      if (m) {
        sh.push(x * px + 'px ' + y * px + 'px 0 ' + m);
      }
    })
  );
  return '<div class="spr" style="width:' + 8 * px + 'px;height:' + rows.length * px + 'px"><i style="width:' + px +
    'px;height:' + px + 'px;box-shadow:' + sh.join(',') + '"></i></div>';
}

const ST = { running: 'working', blocked: 'blocked', idle: 'idle', offline: 'offline' };

function bubble(b) {
  const lv = liveStatus(b);
  if (lv.status === 'running') {
    return '<span class="bub' + (lv.label ? ' live' : '') + '" title="' + esc(lv.label || '') + '">' +
      (lv.label ? esc(lv.label) : '...') + '</span>';
  }
  if (lv.status === 'blocked') {
    return '<span class="bub blocked">! ' + Number(b.blocked) + '</span>';
  }
  if (lv.status === 'offline') {
    return '<span class="bub offline">x</span>';
  }
  return '<span class="bub idle">z</span>';
}
