/**
 * HXCS 社区商店 —— 插件自带配置界面的前端逻辑。
 *
 * # 这个文件跑在哪里
 *
 * 它跑在平台的 `<iframe sandbox="allow-scripts">` 里（**不带** allow-same-origin）：
 *   · 源是不透明的 `null` ⇒ 与平台不同源，读不到平台的 localStorage/sessionStorage；
 *   · 平台静态路由下发 `connect-src 'none'` ⇒ **本文件一次网络请求都不能发**；
 *   · 平台的全部鉴权是 `Authorization: Bearer`，令牌在宿主页面里 ⇒ 本文件也拿不到。
 *
 * 所以所有数据交互只能经 postMessage 求宿主代办。契约（与平台侧
 * `pluginUiProtocol.ts` 逐字对齐，改一侧就必须改另一侧）：
 *
 *   ① 握手（扁平 postMessage，宿主 → 本页）
 *        { hx: 1, type: 'connect', plugin_id }
 *      并**随帧转移**一个 MessagePort（event.ports[0]）。
 *
 *   ② 此后所有业务帧走**那个端口**，不再用 window.postMessage。
 *      为什么必须换通道（而不是一直用 window.postMessage）：window 引用在 iframe
 *      **自导航之后依然成立**（同一个 browsing context 换了文档），于是被导航过去的
 *      第三方页面既收得到宿主投来的数据、也发得进命令。MessagePort 属于**文档**，
 *      文档一换端口就死了 —— 这是平台侧 SEC-B1 的修法，本页只是它的另一端。
 *
 *   ③ 存活探测（宿主 → 本页，**走端口**）
 *        { hx: 1, type: 'ping' }  ⇒  必须回 { hx: 1, type: 'pong', plugin_id }
 *      宿主用它判"这个 browsing context 还是不是我们那份文档"。**不回 pong 的后果**：
 *      iframe 发生第二次 load（哪怕只是导航被 CSP 拦下）时，宿主收不到 pong 就按
 *      "文档已换"处理 ⇒ `detach('navigated')` **永久切断**通道，界面从此收不到任何
 *      数据（表现为"加载完就一直是空的"）。这是本文件**必须**实现 ping/pong 的原因。
 *
 *   ④ 业务帧（本页 → 宿主，走端口）
 *        请求  { hx: 1, id, op, payload }
 *        应答  { hx: 1, id, ok: true,  result }
 *              { hx: 1, id, ok: false, error: { code, message } }
 *      `id` 由本页生成且**每次唯一**（宿主按 id 对账；重复 id 会被拒）。
 *      可用 op（平台白名单，只有这三条）：
 *        · plugin.config.get   → 读配置
 *        · plugin.config.save  → 存配置（**整体替换**语义）
 *        · plugin.tool.call    → 调插件在 manifest 里声明的工具
 *
 *   ⑤ 宿主就绪（宿主 → 本页，走端口）
 *        { hx: 1, type: 'host-ready', plugin_id }
 *      端口是文档打开后才交出来的，页面脚本可能比它早跑 ⇒ 收到这条再发首个请求。
 *      （本页还额外做了一次主动 config.get，两条路都能到，见 boot()。）
 *
 * # 为什么是经典脚本、不是 ES module
 * 不透明源下 `<script type="module">` 要走 CORS，会被浏览器拦（实测）。经典脚本没有
 * 这条限制，且本页不需要 import 任何东西。文件末尾还挂了 window.__hxcsUi 方便排障。
 */
(function () {
  'use strict';

  /** 协议版本。与平台常量 PLUGIN_UI_PROTOCOL 必须相等（不匹配的帧一律被丢弃）。 */
  var HX = 1;

  /**
   * 调用超时（毫秒）。
   *
   * 平台侧对每次 RPC 有自己的 15s 超时并会回一个 `PLUGIN_UI_TIMEOUT` 错误帧；
   * 这里再设一个**略长**的兜底，是为了覆盖"端口还在、但宿主那条 promise 已被丢弃"
   * 的极端情形 —— 没有它，界面会永远停在"测试中…"。
   * 取 18s（> 平台 15s）让平台的错误帧优先到达，本兜底只在平台也失声时才触发。
   */
  var RPC_TIMEOUT_MS = 18000;

  /** 配置键名（与 manifest.config_schema 逐字对齐）。 */
  var KEYS = {
    community: 'community_enabled',
    registry: 'registry_url',
    ha: 'ha_compat_enabled',
    proxy: 'proxy_url',
  };

  /** 兜底默认值（仅当 manifest 的 default 与当前值都拿不到时用）。 */
  var FALLBACK = {
    community_enabled: false,
    registry_url: 'https://raw.githubusercontent.com/1169892406/HXCS/main',
    ha_compat_enabled: false,
    proxy_url: '',
  };

  // ---------------------------------------------------------------- 传输层

  /** 握手交出的端口（收到 connect 之前为 null）。 */
  var port = null;
  /** 本页的 plugin_id —— pong 帧要原样带回。 */
  var pluginId = '';
  /** 在途请求：id → {resolve, reject, timer}。 */
  var pending = {};
  var seq = 0;
  /** 端口是否已建立（决定 UI 上那句连接状态）。 */
  var connected = false;
  /**
   * 通道是否已被宿主判死（收到 frame-navigated 之类）。
   * 只用于把界面状态说清楚，不再做任何"自动重连" —— 重连必须由用户点「重新加载」，
   * 那是平台组件的 reloadSeq，会重建桥。
   */
  var channelDead = false;
  /** 已回的 pong 帧数与最后一帧（仅形状，供排障/闸门断言）。 */
  var pongCount = 0;
  var lastPongSent = null;

  function nextId() {
    seq += 1;
    return 'ui-' + Date.now().toString(36) + '-' + seq.toString(36);
  }

  /** 把一帧投给宿主。没有端口时返回 false（调用方据此给友好提示）。 */
  function send(frame) {
    if (!port) return false;
    try {
      port.postMessage(frame);
      return true;
    } catch (e) {
      return false;
    }
  }

  /**
   * 发一次 RPC。返回 Promise<result>；失败 reject 一个带 code 的 Error。
   *
   * 三个清理点（缺一个就会漏）：settle 时清 timer、删 pending，超时也走同一条路。
   */
  function rpc(op, payload) {
    return new Promise(function (resolve, reject) {
      if (!port) {
        reject(makeErr('PLUGIN_UI_FRAME_NOT_ATTACHED', '还没有连上平台（稍等片刻或点「测试连通」重试）'));
        return;
      }
      var id = nextId();
      var timer = setTimeout(function () {
        if (pending[id]) {
          delete pending[id];
          reject(makeErr('PLUGIN_UI_TIMEOUT', '平台没有在超时内应答（可以重试）'));
        }
      }, RPC_TIMEOUT_MS);
      pending[id] = { resolve: resolve, reject: reject, timer: timer };
      var frame = { hx: HX, id: id, op: op };
      if (payload !== undefined) frame.payload = payload;
      if (!send(frame)) {
        delete pending[id];
        clearTimeout(timer);
        reject(makeErr('PLUGIN_UI_FRAME_NOT_ATTACHED', '通信通道尚未建立'));
      }
    });
  }

  function makeErr(code, message) {
    var e = new Error(message || code);
    e.code = code;
    return e;
  }

  /** 端口来帧的统一入口：pong / 业务应答 / 其它（含 host-ready）。 */
  function onPortMessage(event) {
    var m = event && event.data;
    if (!m || typeof m !== 'object') return;

    // ③ 存活探测：必须回 pong，否则宿主会把本页判成"换了文档"并永久切断。
    if (m.type === 'ping') {
      var pongFrame = { hx: HX, type: 'pong', plugin_id: pluginId };
      send(pongFrame);
      // 只记**形状**（不含任何配置值），供浏览器闸门断言字段名/版本号真的对。
      lastPongSent = pongFrame;
      pongCount += 1;
      return;
    }

    // ⑤ 宿主就绪：这是"可以开始发请求了"的信号。
    if (m.type === 'host-ready') {
      connected = true;
      renderConn();
      if (firstLoadPending) {
        firstLoadPending = false;
        doLoadConfig();
      }
      return;
    }

    // ④ 业务应答：按 id 结算。
    if (typeof m.id === 'string' && typeof m.ok === 'boolean') {
      var p = pending[m.id];
      if (!p) return; // 迟到的应答（我方已超时）——丢弃，不二次结算
      delete pending[m.id];
      clearTimeout(p.timer);
      if (m.ok) {
        p.resolve(m.result);
      } else {
        var err = m.error || {};
        p.reject(makeErr(err.code || 'PLUGIN_UI_HANDLER_FAILED', err.message || '平台拒绝了这次操作'));
      }
      return;
    }
  }

  /** 收下宿主交来的端口。**一帧一次**：已有端口就不再接受（宿主侧同样一帧只交一次）。 */
  function onWindowMessage(event) {
    var m = event && event.data;
    if (!m || typeof m !== 'object' || m.type !== 'connect' || m.hx !== HX) return;
    if (port) return; // 已经接上，忽略重复握手
    var p = event.ports && event.ports[0];
    if (!p) return;
    port = p;
    pluginId = typeof m.plugin_id === 'string' ? m.plugin_id : '';
    connected = true;
    // DOM 规范：addEventListener('message') **不会**隐式启动端口（只有设置 onmessage 会）。
    // 不显式 start 的端口会把消息静默丢弃 —— 表现为"宿主发来的帧永远到不了本页"。
    // 这里用 onmessage = fn 的形式（它本身就会启动端口），并在有 start 时再显式调一次。
    port.onmessage = onPortMessage;
    if (typeof port.start === 'function') {
      try { port.start(); } catch (e) { /* 已启动 */ }
    }
    renderConn();
    if (firstLoadPending) {
      firstLoadPending = false;
      doLoadConfig();
    }
  }

  window.addEventListener('message', onWindowMessage);

  // ---------------------------------------------------------------- 状态与渲染

  /** 当前表单（与 baseline 比较判 dirty）。 */
  var form = clone(FALLBACK);
  /** 载入时的基线：保存按钮是否可点由它决定。 */
  var baseline = clone(FALLBACK);
  /** manifest schema 的 properties（取 default 用）。 */
  var schemaProps = {};
  var loading = true;
  var saving = false;
  var probing = false;
  /** 首次 config.get 是否还没发出（收到 connect / host-ready 之前挂起）。 */
  var firstLoadPending = true;
  /** 已保存过一次？用于"保存后 reload"的时序。 */
  var meta = { name: '', version: '' };

  function clone(o) {
    return JSON.parse(JSON.stringify(o));
  }

  function $(id) {
    return document.getElementById(id);
  }

  /* 2026-11-08 用户裁定：「已连接平台」chip 删除 —— 插件随平台服务自动加载，
     连接状态没有信息量。通道死亡（channelDead）时由 banner 报错，不靠常驻 chip。 */
  function renderConn() {}

  /** 开关的状态文字（纯展示，与控件 aria-checked 同源）。 */
  function renderToggles() {
    var c = $('community-state');
    if (c) c.textContent = form[KEYS.community] ? '已启用' : '已关闭';
    var h = $('ha-state');
    if (h) h.textContent = form[KEYS.ha] ? '已开启' : '已关闭';
    var swC = $('sw-community');
    if (swC) swC.setAttribute('aria-checked', form[KEYS.community] ? 'true' : 'false');
    var swH = $('sw-ha');
    if (swH) swH.setAttribute('aria-checked', form[KEYS.ha] ? 'true' : 'false');
  }

  /** 输入框回显（只在载入时写，避免用户打字时被覆盖）。 */
  function renderInputs() {
    var r = $('in-registry');
    if (r && document.activeElement !== r) r.value = form[KEYS.registry] || '';
    var p = $('in-proxy');
    if (p && document.activeElement !== p) p.value = form[KEYS.proxy] || '';
  }

  function isDirty() {
    return JSON.stringify(form) !== JSON.stringify(baseline);
  }

  function renderSave() {
    var btn = $('btn-save');
    if (!btn) return;
    btn.disabled = loading || saving || !isDirty() || channelDead;
    btn.textContent = saving ? '保存中…' : '保存配置';
  }

  function setBanner(kind, text) {
    var el = $('state-banner');
    if (!el) return;
    if (!text) {
      el.innerHTML = '';
      return;
    }
    var cls = kind === 'err' ? 'banner banner--err' : kind === 'info' ? 'banner banner--info' : 'banner banner--warn';
    el.innerHTML = '';
    var div = document.createElement('div');
    div.className = cls;
    div.setAttribute('data-testid', 'hxcs-ui-banner');
    div.textContent = text;
    el.appendChild(div);
  }

  /** 把不可信错误信息里最常见的网络故障翻译成人话（与平台页面同一口径）。 */
  function friendlyNetErr(raw) {
    var s = String(raw || '');
    if (/timeout|timed out|broken pipe|EOF|network|unreachable|Connection refused/i.test(s)) {
      return '地址访问超时：' + (form[KEYS.registry] || '注册表') +
        ' 不可达（直连慢或被阻断）。可在「下载代理」配置代理后保存并重试';
    }
    return s;
  }

  // ---------------------------------------------------------------- 六项功能

  /** 读配置：plugin.config.get。 */
  function doLoadConfig() {
    loading = true;
    renderSave();
    setBanner('info', '');

    rpc('plugin.config.get')
      .then(function (res) {
        var cfg = (res && res.config) || {};
        var schema = (res && res.config_schema) || {};
        schemaProps = (schema && schema.properties) || {};
        meta.name = (res && res.plugin_id) || '';
        meta.version = (res && res.version) || '';
        var next = formFrom(cfg, schemaProps);
        form = next;
        baseline = clone(next);
        loading = false;
        var title = $('plugin-title');
        if (title && meta.name) title.textContent = meta.name;
        renderToggles();
        renderInputs();
        renderSave();
        // 功能 6：社区状态展示（开关打开时才拉，避免关闭状态下的无意义错误）
        renderCatalogPlaceholder();
        if (form[KEYS.community]) void loadCatalog();
      })
      .catch(function (e) {
        loading = false;
        renderSave();
        var code = (e && e.code) || '';
        if (code === 'PERM_FORBIDDEN' || code === 'PLUGIN_PERMISSION_DENIED') {
          setBanner('warn', '读不到配置是权限问题（需要 plugin.manage），不是这个插件没有配置项。');
        } else if (code === 'PLUGIN_NOT_FOUND') {
          setBanner('warn', '这个家庭还没有 HXCS 插件的实例。');
        } else if (code === 'PLUGIN_UI_FRAME_NOT_ATTACHED') {
          // 通道还没建立：不是错误，等 connect / host-ready 会重试一次
          firstLoadPending = true;
          setBanner('info', '正在等待与平台建立通道…');
        } else {
          setBanner('err', '配置读取失败：' + ((e && e.message) || code));
        }
      });
  }

  /**
   * manifest default 优先、当前值次之、最后 FALLBACK —— 与平台页面 formFrom 同一口径。
   * 差异：本页**不**把空串当成"有效值"以外的特殊情形（HXCS 的 proxy_url 空串就是直连）。
   */
  function formFrom(cfg, props) {
    function pick(key) {
      if (key in cfg) return cfg[key];
      var d = props && props[key] ? props[key].default : undefined;
      return d;
    }
    function asBool(v, fb) {
      return typeof v === 'boolean' ? v : fb;
    }
    function asStr(v, fb) {
      if (typeof v === 'string' && v) return v;
      return fb;
    }
    return {
      community_enabled: asBool(pick(KEYS.community), FALLBACK.community_enabled),
      registry_url: asStr(pick(KEYS.registry), FALLBACK.registry_url),
      ha_compat_enabled: asBool(pick(KEYS.ha), FALLBACK.ha_compat_enabled),
      // proxy_url：空串是**合法且有含义**的值（= 直连），不能用 asStr 把空串变成 FALLBACK
      proxy_url: typeof pick(KEYS.proxy) === 'string' ? pick(KEYS.proxy) : FALLBACK.proxy_url,
    };
  }

  /** 保存：plugin.config.save（整体替换）。 */
  function doSave() {
    if (saving || loading) return;
    saving = true;
    renderSave();
    rpc('plugin.config.save', { config: clone(form) })
      .then(function () {
        saving = false;
        setBanner('info', '已保存社区商店配置（配置热生效，不需要重启服务）');
        // 保存后重读一次：以**服务端**为准重建基线（而不是把本地值当成已保存的事实）
        doLoadConfig();
        if (form[KEYS.community]) void loadCatalog();
      })
      .catch(function (e) {
        saving = false;
        renderSave();
        var code = (e && e.code) || '';
        var msg = (e && e.message) || '';
        setBanner('err', '保存失败' + (code ? '［' + code + '］' : '') + '：' + msg);
      });
  }

  /** 功能 3：测试连通。**经 plugin.tool.call 调 catalog_list**，不 direct fetch。 */
  function doProbe() {
    if (probing) return;
    var out = $('probe-result');
    probing = true;
    var btn = $('btn-probe');
    if (btn) btn.textContent = '测试中…';
    if (out) {
      out.className = 'note';
      out.textContent = '正在经插件探测注册表…';
    }

    function done(kind, text) {
      probing = false;
      if (btn) btn.textContent = '测试连通';
      if (out) {
        out.className = 'note ' + (kind === 'ok' ? 'note--ok' : 'note--bad');
        out.textContent = (kind === 'ok' ? '✅ ' : '❌ ') + text;
      }
    }

    // 先落盘再探测：catalog_list 读的是**已保存**的 registry_url / proxy_url。
    // 直接探测会让用户以为"改了地址立刻就测了"，而插件侧用的还是旧值 —— 那种
    // "测试结果与界面显示不一致"最难解释。所以这里明确先保存再测。
    var needSave = isDirty();
    var chain = needSave
      ? rpc('plugin.config.save', { config: clone(form) }).then(function () {
          baseline = clone(form);
          renderSave();
          return null;
        })
      : Promise.resolve(null);

    chain
      .then(function () {
        return rpc('plugin.tool.call', { tool: 'catalog_list', args: {} });
      })
      .then(function (res) {
        // 宿主把 /invoke/ 的两种结果都翻译成统一形状：
        //   成功 → data（即插件 catalog_list 的返回：{registry_version, trust_root, plugins:[…]}）
        //   业务失败（200 + ok:false）→ {ok:false, kind, message}
        if (res && res.ok === false) {
          done('bad', friendlyNetErr(res.message || '注册表不可达'));
          return;
        }
        var plugins = (res && res.plugins) || [];
        var root = (res && res.trust_root) || {};
        var prebuilt = plugins.filter(function (p) {
          return p && p.type !== 'ha_integration';
        });
        done(
          'ok',
          '可访问 · ' + prebuilt.length + ' 个插件 · 信任根 ' + (root.key_id || '—')
        );
        // 探测成功顺手把社区状态刷新一次（同一次数据，不额外发请求）
        renderCatalog({ data: res });
      })
      .catch(function (e) {
        var code = (e && e.code) || '';
        if (code === 'PLUGIN_UI_TOOL_NOT_ALLOWED') {
          done('bad', '平台没有放行 catalog_list 工具调用（manifest.tools 未声明或宿主白名单为空）');
          return;
        }
        if (code === 'PLUGIN_UI_FRAME_NOT_ATTACHED') {
          done('bad', '还没有连上平台，请稍后重试');
          return;
        }
        done('bad', friendlyNetErr((e && e.message) || code || '注册表不可达'));
      });
  }

  /** 功能 6：社区状态展示 —— 调 catalog_list 拿插件数。 */
  var catalogSeq = 0;
  function loadCatalog() {
    var my = ++catalogSeq;
    var body = $('catalog-body');
    if (body) {
      body.innerHTML = '';
      var d = document.createElement('div');
      d.className = 'desc';
      d.textContent = '读取注册表…';
      body.appendChild(d);
    }
    rpc('plugin.tool.call', { tool: 'catalog_list', args: {} })
      .then(function (res) {
        if (my !== catalogSeq) return; // 有更新的请求在跑，丢弃旧结果
        renderCatalog({ data: res });
      })
      .catch(function (e) {
        if (my !== catalogSeq) return;
        renderCatalog({ error: e });
      });
  }

  function renderCatalogPlaceholder() {
    var body = $('catalog-body');
    if (!body) return;
    body.innerHTML = '';
    var d = document.createElement('div');
    d.className = 'desc';
    d.textContent = form[KEYS.community]
      ? '读取注册表…'
      : '社区插件未启用：打开上方开关并保存后，此处显示注册表内容。';
    body.appendChild(d);
  }

  /** 渲染社区内容。`{data}` 成功；`{error}` 失败。 */
  function renderCatalog(outcome) {
    var body = $('catalog-body');
    if (!body) return;
    body.innerHTML = '';

    if (outcome.error) {
      var e = outcome.error;
      var code = (e && e.code) || '';
      var div = document.createElement('div');
      if (code === 'PLUGIN_UI_TOOL_NOT_ALLOWED') {
        div.className = 'note';
        div.textContent = '平台没有放行 catalog_list 调用：请确认插件 manifest 声明了该工具。';
      } else {
        div.className = 'note';
        div.textContent = '注册表读取失败：' + friendlyNetErr((e && e.message) || code) + '（可点「测试连通」排查）';
      }
      div.setAttribute('data-testid', 'hxcs-ui-catalog-error');
      body.appendChild(div);
      return;
    }

    var res = outcome.data || {};
    // 业务失败（插件回 200 + ok:false）
    if (res.ok === false) {
      var d0 = document.createElement('div');
      d0.className = 'note';
      d0.textContent = '注册表读取失败：' + friendlyNetErr(res.message || '插件返回失败') + '（可点「测试连通」排查）';
      d0.setAttribute('data-testid', 'hxcs-ui-catalog-error');
      body.appendChild(d0);
      return;
    }

    var plugins = res.plugins || [];
    var root = res.trust_root || {};
    // ## 「注册插件」左右两列表格（用户 2026-11-08 确认的效果稿）
    //
    // · 左列「HACS 插件」= type:ha_integration（HA 集成包，经 worker 的
    //   integration_install 通道安装进 HA 兼容运行时）
    // · 右列「HXCS 插件」= 其余（平台 .hpkg 包，经平台 installFromPackage 安装）
    // 两组都展示 —— 之前把 ha_integration 过滤掉不显示，用户看不到注册表里的
    // HA 集成有哪些。短列用 — 补位；表尾一行汇总数量与信任根。
    var hacs = plugins.filter(function (p) { return p && p.type === 'ha_integration'; });
    var hxcs = plugins.filter(function (p) { return p && p.type !== 'ha_integration'; });
    var rows = Math.max(hacs.length, hxcs.length, 1);

    var tbl = document.createElement('table');
    tbl.className = 'reg-table';
    tbl.setAttribute('data-testid', 'hxcs-ui-catalog-table');

    var thead = document.createElement('thead');
    var htr = document.createElement('tr');
    ['HACS 插件', 'HXCS 插件'].forEach(function (t) {
      var th = document.createElement('th');
      th.textContent = t;
      htr.appendChild(th);
    });
    thead.appendChild(htr);
    tbl.appendChild(thead);

    var tbody = document.createElement('tbody');
    for (var i = 0; i < rows; i++) {
      var tr = document.createElement('tr');
      [hacs[i], hxcs[i]].forEach(function (p) {
        var td = document.createElement('td');
        if (!p) {
          td.textContent = '—';
          td.className = 'reg-table__empty';
        } else {
          td.setAttribute('data-testid', 'hxcs-ui-catalog-item-' + (p.plugin_id || ''));
          var b = document.createElement('b');
          b.textContent = p.name || p.plugin_id || '未命名';
          var v = document.createElement('span');
          v.className = 'mono';
          v.textContent = ' v' + (p.version || '—');
          var lic = document.createElement('span');
          lic.className = 'reg-table__lic';
          lic.textContent = (p.license ? ' ' + p.license : '');
          td.appendChild(b);
          td.appendChild(v);
          td.appendChild(lic);
        }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    }
    tbl.appendChild(tbody);
    body.appendChild(tbl);

    var foot = document.createElement('div');
    foot.className = 'reg-table__foot';
    var fp = String(root.fingerprint || '').slice(0, 16);
    foot.textContent =
      'HACS ' + hacs.length + ' 个 · HXCS ' + hxcs.length + ' 个 · 信任根：' +
      (root.key_id || '—') + '（指纹 ' + (fp || '—') + '）';
    body.appendChild(foot);
  }

  // ---------------------------------------------------------------- 事件接线

  function onSwitch(key, stateEl) {
    form[key] = !form[key];
    renderToggles();
    renderSave();
    // 开关变化即影响"社区内容"区块的显示条件（未启用时不该显示注册表内容）
    if (key === KEYS.community) {
      if (form[KEYS.community]) {
        void loadCatalog();
      } else {
        renderCatalogPlaceholder();
      }
    }
    void stateEl;
  }

  document.addEventListener('DOMContentLoaded', function () {
    var swC = $('sw-community');
    if (swC) swC.addEventListener('click', function () { onSwitch(KEYS.community, $('community-state')); });
    var swH = $('sw-ha');
    if (swH) swH.addEventListener('click', function () { onSwitch(KEYS.ha, $('ha-state')); });

    var inR = $('in-registry');
    if (inR) {
      inR.addEventListener('input', function () {
        form[KEYS.registry] = inR.value;
        renderSave();
      });
    }
    var inP = $('in-proxy');
    if (inP) {
      inP.addEventListener('input', function () {
        form[KEYS.proxy] = inP.value;
        renderSave();
      });
    }

    var save = $('btn-save');
    if (save) save.addEventListener('click', doSave);
    var probe = $('btn-probe');
    if (probe) probe.addEventListener('click', doProbe);

  // 返回插件列表：iframe（opaque origin）不能操作顶层导航 —— 走协议 op
  // plugin.ui.close（容器执行 onClose；去哪由宿主决定，插件不指定地址）。
  var back = $('btn-back');
  if (back) back.addEventListener('click', function () {
    rpc('plugin.ui.close')
      .catch(function () { /* 容器不支持该 op 时静默：按钮仍在，不藏功能 */ });
  });

    renderConn();
    renderToggles();
    renderInputs();
    renderSave();
    renderCatalogPlaceholder();

    // 主动发一次 config.get：connect 帧可能在脚本执行前就到了（那时 firstLoadPending
    // 已被消费），而更常见的是 connect 还没到 —— 这条请求会因无端口而失败，
    // 失败处把 firstLoadPending 置回 true，等 connect/host-ready 再发一次。
    // 两条路都收敛到"最多各发一次"，不会打双份请求。
    doLoadConfig();
  });

  // 出站端口若被宿主关掉，把状态说清楚（不做自动重连 — 那是平台组件的 reloadSeq）。
  window.addEventListener('pagehide', function () {
    channelDead = true;
    renderConn();
  });

  /* 排障用：真实浏览器闸门可以读它判断"握手成了没有"。**不含任何配置值**。 */
  window.__hxcsUi = {
    probe: function () {
      return {
        connected: connected,
        hasPort: !!port,
        pluginId: pluginId,
        pending: Object.keys(pending).length,
        pongCount: pongCount,
        lastPong: lastPongSent,
        channelDead: channelDead,
      };
    },
    version: 1,
  };
})();