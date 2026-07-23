let emails = [];
let filtered = [];

const $ = (id) => document.getElementById(id);

async function fetchEmails() {
  const res = await fetch('/api/emails');
  const data = await res.json();
  emails = data.emails;
  filtered = emails;
  $('totalCount').textContent = data.total;
  renderEmails();
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function renderEmails() {
  const list = $('emailList');
  list.innerHTML = filtered.map(e => `
    <div class="email-item" data-id="${e.id}">
      <div>
        <p class="meta">#${e.id} · ${escapeHtml(e.sender)} · ${escapeHtml(e.date)}</p>
        <h3>${escapeHtml(e.subject)}</h3>
        <p>${escapeHtml(e.body.slice(0, 92))}${e.body.length > 92 ? '...' : ''}</p>
      </div>
      <div class="attachment">${e.attachment ? '첨부' : ''}</div>
    </div>
  `).join('');
}

function openEmail(id) {
  const e = emails.find(x => x.id === id);
  if (!e) return;
  $('dialogDate').textContent = `#${e.id} · ${e.date}`;
  $('dialogSubject').textContent = e.subject;
  $('dialogSender').textContent = e.sender;
  $('dialogAttachment').textContent = e.attachment || '없음';
  $('dialogBody').textContent = e.body;
  $('emailDialog').showModal();
}

function applySearch() {
  const q = $('searchInput').value.toLowerCase().trim();
  filtered = emails.filter(e => `${e.sender} ${e.subject} ${e.body}`.toLowerCase().includes(q));
  renderEmails();
}

async function runFilter() {
  const systemPrompt = $('systemPromptBox').value.trim();
  const prompt = $('promptBox').value.trim();
  const username = $('username').value.trim() || 'anonymous';
  if (!systemPrompt) {
    alert('시스템 프롬프트를 입력하세요.');
    return;
  }
  if (!prompt) {
    alert('탐지 프롬프트를 입력하세요.');
    return;
  }

  $('runBtn').disabled = true;
  $('runBtn').textContent = 'AI 분석 중...';
  resetProgress();

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${protocol}//${window.location.host}/ws/run`);
  let finished = false;
  let closingExpected = false;

  ws.addEventListener('open', () => {
    addProgress('연결', '서버에 연결됨');
    ws.send(JSON.stringify({ username, system_prompt: systemPrompt, prompt }));
  });

  ws.addEventListener('message', async (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'progress') {
      const perBatch = data.stage === 'generating' || data.stage === 'parsed';
      addProgress(formatStage(data.stage), formatProgressMessage(data), perBatch);
      if (perBatch) {
        setProgressBar(data.stage === 'parsed' ? data.index : data.index - 1, data.total);
      }
      return;
    }
    if (data.type === 'final') {
      finished = true;
      closingExpected = true;
      addProgress('완료', '분석 완료');
      renderResult(data);
      await fetchLeaderboard();
      ws.close();
      return;
    }
    if (data.type === 'error') {
      finished = true;
      closingExpected = true;
      addProgress('오류', data.error);
      alert(`오류: ${data.error}`);
      ws.close();
    }
  });

  ws.addEventListener('error', () => {
    if (finished || closingExpected) return;
    finished = true;
    addProgress('오류', '연결 실패');
    alert('오류: WebSocket 연결에 실패했습니다.');
  });

  ws.addEventListener('close', () => {
    if (!finished && !closingExpected) {
      addProgress('오류', '분석이 끝나기 전에 연결이 닫힘');
    }
    $('runBtn').disabled = false;
    $('runBtn').textContent = '실행';
  });
}

function formatStage(stage) {
  const labels = {
    queued: '대기',
    connecting: '연결',
    waiting: '대기',
    generating: '분석',
    parsed: '분석',
    scoring: '채점',
    saved: '저장',
  };
  return labels[stage] || stage;
}

function formatProgressMessage(data) {
  const { stage, index, total } = data;
  if (stage === 'queued') return '요청 접수';
  if (stage === 'connecting') return 'Ollama 연결 중';
  if (stage === 'waiting') return `모델 응답 대기 중 (${total ?? '?'}개 묶음)`;
  if (stage === 'generating') return `메일 분석 중 ${index}/${total}`;
  if (stage === 'parsed') return `${index}/${total} 완료 · 삭제 ${data.deleted}`;
  if (stage === 'scoring') return '점수 계산';
  if (stage === 'saved') return '리더보드 저장';
  return data.message;
}

function resetProgress() {
  $('progressBox').classList.remove('hidden');
  $('progressList').innerHTML = '';
  setProgressBar(0, 0);
}

function setProgressBar(index, total) {
  const bar = $('progressBar');
  const fill = $('progressFill');
  if (!total) {
    bar.classList.add('hidden');
    return;
  }
  bar.classList.remove('hidden');
  fill.style.width = `${Math.round((index / total) * 100)}%`;
}

// Per-batch updates rewrite one row instead of appending 20+ near-identical lines.
function addProgress(stage, message, live = false) {
  const list = $('progressList');
  if (live) {
    let item = list.querySelector('.progress-item.live');
    if (!item) {
      item = document.createElement('div');
      item.className = 'progress-item live';
      list.appendChild(item);
    }
    item.innerHTML = `<b>${escapeHtml(stage)}</b><span>${escapeHtml(message)}</span>`;
    list.scrollTop = list.scrollHeight;
    return;
  }
  const item = document.createElement('div');
  item.className = `progress-item ${stage === '오류' ? 'error' : ''}`;
  item.innerHTML = `<b>${escapeHtml(stage)}</b><span>${escapeHtml(message)}</span>`;
  list.appendChild(item);
  list.scrollTop = list.scrollHeight;
}

function renderResult(data) {
  $('resultBox').classList.remove('hidden');
  $('score').textContent = data.result.score;
  $('tp').textContent = data.result.tp;
  $('fp').textContent = data.result.fp;
  $('fn').textContent = data.result.fn;
  $('engine').textContent = `삭제 ${data.result.deleted_count} · precision ${data.result.precision} · recall ${data.result.recall}`;

  const reveal = $('revealList');
  if (!data.reveal.length) {
    reveal.textContent = '삭제되거나 놓친 메일이 없습니다.';
    return;
  }
  reveal.classList.remove('muted');
  reveal.innerHTML = data.reveal.map(r => `
    <div class="reveal-item">
      <span class="tag ${r.result}">${r.result}</span>
      <b>#${r.id}</b> ${escapeHtml(r.subject)}<br>
      <span class="muted">${escapeHtml(r.sender)} · 실제 정답: ${r.is_malicious ? '악성' : '정상'}</span><br>
      ${r.indicators?.length ? `<span class="muted">특징: ${r.indicators.map(escapeHtml).join(', ')}</span>` : ''}
    </div>
  `).join('');
}

async function fetchLeaderboard() {
  const res = await fetch('/api/leaderboard');
  const data = await res.json();
  const body = $('leaderboardBody');
  body.innerHTML = data.leaderboard.map((r, i) => `
    <tr>
      <td>${i + 1}</td>
      <td>${escapeHtml(r.username)}</td>
      <td><b>${r.score}</b></td>
      <td>${r.tp}</td>
      <td>${r.fp}</td>
      <td>${r.fn}</td>
      <td>${r.deleted_count}</td>
      <td>${escapeHtml(r.created_at)}</td>
    </tr>
  `).join('') || '<tr><td colspan="8" class="muted">아직 기록이 없습니다.</td></tr>';
}

// One delegated listener, so re-rendering the list on every keystroke stays cheap.
$('emailList').addEventListener('click', (event) => {
  const item = event.target.closest('.email-item');
  if (item) openEmail(Number(item.dataset.id));
});

$('searchInput').addEventListener('input', applySearch);
$('runBtn').addEventListener('click', runFilter);
$('refreshBtn').addEventListener('click', fetchLeaderboard);
$('closeDialog').addEventListener('click', () => $('emailDialog').close());

fetchEmails();
fetchLeaderboard();
