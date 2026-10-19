<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { api, json, streamPost } from './api';
interface Library { id: string; name: string }
interface Document { id: string; name: string; status: string; error: string }
interface Source { id: string; name: string; page: number; paragraph: number; heading: string; text: string; score: number }
const libraries = ref<Library[]>([]), docs = ref<Document[]>([]), selected = ref(''), name = ref('技术手册');
const question = ref('如何处理 API 请求失败后的重试？'), strategy = ref('hybrid'), answer = ref(''), sources = ref<Source[]>([]);
const error = ref(''), busy = ref(false), mode = ref('demo'), elapsed = ref<number | null>(null), valid = ref(true), uploadBusy = ref(false);
const current = computed(() => libraries.value.find(l => l.id === selected.value));
const ready = computed(() => docs.value.filter(d => d.status === 'ready').length);
let poll: ReturnType<typeof setInterval>;
async function reload() { if (selected.value) docs.value = await api<Document[]>(`/api/libraries/${selected.value}/documents`); }
async function choose(id: string) { selected.value = id; answer.value = ''; sources.value = []; await reload(); }
async function create() { try { const lib = await api<Library>('/api/libraries', json({name:name.value})); libraries.value.unshift(lib); await choose(lib.id); } catch(e) { error.value = String(e); } }
async function upload(event: Event) {
  const input = event.target as HTMLInputElement; if (!input.files?.length) return; uploadBusy.value = true; error.value = '';
  try { for (const file of Array.from(input.files)) { const form = new FormData(); form.append('file', file); await api(`/api/libraries/${selected.value}/documents`, {method:'POST',body:form}); } await reload(); }
  catch(e) { error.value = String(e); } finally { uploadBusy.value = false; input.value = ''; }
}
async function remove(id: string) { try { await api(`/api/documents/${id}`, {method:'DELETE'}); await reload(); sources.value = []; answer.value = ''; } catch(e) { error.value = String(e); } }
async function retry(id: string) { try { await api(`/api/documents/${id}/retry`, {method:'POST'}); await reload(); } catch(e) { error.value = String(e); } }
async function ask(debug = false) {
  error.value = ''; busy.value = true; answer.value = ''; sources.value = []; elapsed.value = null; valid.value = true;
  try {
    const body = {question:question.value, strategy:strategy.value};
    if (debug) sources.value = await api<Source[]>(`/api/libraries/${selected.value}/search`, json(body));
    else await streamPost(`/api/libraries/${selected.value}/chat`, body, ({event,data}) => {
      if (event === 'sources') sources.value = data as Source[];
      if (event === 'token') answer.value += (data as {text:string}).text;
      if (event === 'error') error.value = (data as {message:string}).message;
      if (event === 'done') { elapsed.value = (data as {elapsed_ms:number}).elapsed_ms; valid.value = (data as {citations_valid:boolean}).citations_valid; }
    });
  } catch(e) { error.value = String(e); } finally { busy.value = false; }
}
const statusLabel: Record<string,string> = {ready:'已建立索引',queued:'等待处理',processing:'正在处理',failed:'处理失败'};
onMounted(async () => { try { mode.value = (await api<{mode:string}>('/api/health')).mode; libraries.value = await api<Library[]>('/api/libraries'); if (libraries.value[0]) await choose(libraries.value[0].id); poll = setInterval(() => { if (docs.value.some(d => ['processing','queued'].includes(d.status))) void reload().catch(() => {}); }, 1500); } catch(e) {error.value=String(e);} });
onUnmounted(() => clearInterval(poll));
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand"><div class="mark">e</div>evidence<span style="color:#91a498">/</span></div>
      <div><div class="eyebrow" style="margin-bottom:14px">WORKSPACE</div><nav class="nav"><button class="active">▤ &nbsp; 知识工作台</button></nav></div>
      <div><div class="eyebrow" style="margin-bottom:14px">YOUR LIBRARIES</div><nav class="nav"><button v-for="lib in libraries" :key="lib.id" :class="{active:selected===lib.id}" @click="choose(lib.id)">◈ &nbsp; {{lib.name}}</button></nav><p v-if="!libraries.length" class="muted">创建你的第一个知识库</p></div>
      <div class="side-note"><strong>每个答案，都有出处。</strong><br>文档与索引保存在本地。真实模式下，相关文本会发送至你配置的模型 API。</div>
    </aside>
    <main class="main">
      <header class="topbar"><span>工作空间 &nbsp; / &nbsp; {{current?.name || '开始探索'}}</span><span class="badge"><span class="dot"></span>{{mode==='demo'?'DEMO · 原文摘录模式':'LIVE · 模型已配置'}}</span></header>
      <section class="hero"><div><div class="eyebrow" style="margin-bottom:13px">KNOWLEDGE, WITH EVIDENCE</div><h1>让文档成为<br>有据可查的答案。</h1><p>从技术手册到接口规范，检索、阅读与追溯都在一个工作台。<br>上传资料，提出问题，沿着引用回到原文。</p></div><div class="hero-art">▤</div></section>
      <div class="stats"><div class="stat"><span>知识库 / LIBRARIES</span><strong>{{String(libraries.length).padStart(2,'0')}}</strong></div><div class="stat"><span>当前已索引文档</span><strong>{{String(ready).padStart(2,'0')}} <small class="muted">/ {{docs.length}}</small></strong></div><div class="stat"><span>检索策略</span><strong style="font-size:19px">{{strategy==='vector'?'Vector':strategy==='rerank'?'Rerank':'Hybrid + RRF'}}</strong></div></div>
      <div v-if="error" role="alert" class="error">{{error}}</div>
      <div class="grid">
        <section>
          <div v-if="!selected" class="card"><div class="card-header"><h2>01 / 建立你的知识库</h2></div><p class="muted">先为这组技术资料取一个名字。</p><div class="row"><input v-model="name" aria-label="知识库名称" placeholder="例如：后端工程手册"><button @click="create" :disabled="!name.trim()">创建知识库 →</button></div></div>
          <div class="card"><div class="card-header"><h2>向知识库提问</h2><span class="muted">01 — ASK</span></div><textarea v-model="question" rows="4" placeholder="你想从这些文档中了解什么？" aria-label="问题"></textarea>
            <div class="chips"><button @click="question='如何处理 API 请求失败后的重试？'">请求失败与重试</button><button @click="question='数据库迁移如何回滚？'">数据库迁移</button><button @click="question='SSE 如何恢复断开的连接？'">流式事件</button></div>
            <div class="row" style="justify-content:space-between;flex-wrap:wrap"><select v-model="strategy" aria-label="检索策略"><option value="hybrid">混合检索 · RRF</option><option value="vector">纯向量检索</option><option value="rerank">混合检索 + 重排</option></select><div class="row"><button class="secondary" @click="ask(true)" :disabled="busy||!selected||!question.trim()">只看检索</button><button @click="ask()" :disabled="busy||!selected||!question.trim()">{{busy?'正在检索…':'生成答案 ↗'}}</button></div></div>
            <div v-if="answer" class="answer-block"><div class="card-header"><span class="eyebrow">ANSWER</span><span v-if="elapsed!==null" class="muted">{{elapsed}} ms</span></div><div class="answer">{{answer}}</div><p v-if="!valid" class="error">回答含有不存在的引用编号，请核对证据。</p></div>
            <div v-else-if="!busy" class="empty">你的下一次发现，从一个问题开始。<br><small>回答引用与原文证据将在这里展示</small></div>
          </div>
          <div v-if="sources.length" class="card"><div class="card-header"><h2>回答背后的证据</h2><span class="muted">{{sources.length}} SOURCES</span></div><details v-for="(source,i) in sources" :key="source.id" class="source" :open="i===0"><summary><span class="number">{{i+1}}</span>{{source.name}} <span class="muted">· 第 {{source.page}} 页</span></summary><p>{{source.text}}</p><div class="muted" style="margin-top:12px">{{source.heading}} · 段落 {{source.paragraph}} · 得分 {{source.score.toFixed(4)}}</div></details></div>
        </section>
        <section><div class="card"><div class="card-header"><h2>文档资料</h2><span class="muted">02 — SOURCES</span></div><label class="upload" :style="!selected?'opacity:.45;pointer-events:none':''"><span style="font-size:26px;color:#6f9b7a">↥</span><strong>{{uploadBusy?'正在上传…':'点击上传你的技术文档'}}</strong><span class="muted">Markdown、TXT、文本 PDF · 单文件 10 MB</span><input type="file" multiple accept=".md,.txt,.pdf" @change="upload" :disabled="!selected||uploadBusy"></label>
          <div v-for="doc in docs" :key="doc.id" class="doc"><div class="doc-name">▤ &nbsp; {{doc.name}}<small>{{statusLabel[doc.status] || doc.status}}{{doc.error?' · '+doc.error:''}}</small></div><div class="row"><button v-if="doc.status==='failed'" class="secondary tiny" @click="retry(doc.id)">重试</button><button class="danger tiny" @click="remove(doc.id)" :disabled="busy" aria-label="删除文档">×</button></div></div><p v-if="!docs.length" class="empty">还没有文档。<br>可上传项目 examples/docs 中的示例资料。</p>
        </div><div class="card"><div class="eyebrow" style="margin-bottom:13px">A CLEARER PATH TO ANSWERS</div><p style="font-size:13px;color:#647f71">01 &nbsp; 按标题整理文档段落<br>02 &nbsp; 结合关键词与向量召回<br>03 &nbsp; 查看每条回答的来源</p><div class="row"><input v-model="name" placeholder="新知识库名称" aria-label="新知识库名称"><button class="secondary tiny" @click="create" :disabled="!name.trim()">＋ 新建</button></div></div></section>
      </div><footer class="footer">EVIDENCE RAG &nbsp; / &nbsp; OPEN SOURCE · LOCAL FIRST · TRACEABLE ANSWERS</footer>
    </main>
  </div>
</template>
