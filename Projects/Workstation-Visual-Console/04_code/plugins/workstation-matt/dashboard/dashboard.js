"use strict";
const labels={pending:"未开始",running:"进行中",blocked:"受阻",completed:"已完成",skipped:"已跳过"};
const state={tasks:[],warnings:[],task:sessionStorage.getItem("matt-task")||"",stage:sessionStorage.getItem("matt-stage")||"",signature:"",controller:null};
const $=selector=>document.querySelector(selector);
const esc=value=>String(value??"").replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const date=value=>value?new Date(value).toLocaleString("zh-CN",{hour12:false}):"尚未记录";
const pill=status=>`<span class="pill ${esc(status)}">${esc(labels[status]||status)}</span>`;

function render(){
  const active=document.activeElement;
  const focus=active?.matches(".task")?["task",active.dataset.task]:active?.matches(".stage")?["stage",active.dataset.stage]:active?.matches(".evidence")?["href",active.getAttribute("href")]:active?.matches("#workspace summary")?["history",""]:null;
  const query=$("#search").value.trim().toLowerCase(),filter=$("#filter").value;
  const tasks=state.tasks.filter(task=>(filter==="all"||task.status===filter)&&`${task.title} ${task.project} ${task.task}`.toLowerCase().includes(query));
  $("#count").textContent=String(tasks.length);
  if(!tasks.some(task=>task.task===state.task)){state.task=tasks[0]?.task||"";state.stage="";}
  $("#tasks").innerHTML=tasks.length?tasks.map(task=>`<button type="button" class="task ${state.task===task.task?"active":""}" data-task="${esc(task.task)}" aria-pressed="${state.task===task.task}"><span class="task-title">${esc(task.title)}</span><span class="task-meta"><span>${esc(task.project)}</span>${pill(task.status)}</span></button>`).join(""):'<p class="nothing">没有符合条件的任务</p>';
  const task=tasks.find(task=>task.task===state.task);
  if(!task){$("#workspace").innerHTML='<div class="empty"><span>m</span><h2>让过程有迹可循</h2><p>使用插件开始一项Matt任务，<br>阶段和验收证据会出现在这里。</p></div>';return;}
  if(!task.stages.some(stage=>stage.id===state.stage))state.stage=(task.stages.find(stage=>stage.status==="running"||stage.status==="blocked")||task.stages.find(stage=>stage.status==="pending")||task.stages.at(-1)).id;
  sessionStorage.setItem("matt-task",state.task);sessionStorage.setItem("matt-stage",state.stage);
  const selected=task.stages.find(stage=>stage.id===state.stage),done=task.stages.filter(stage=>stage.status==="completed").length,skipped=task.stages.filter(stage=>stage.status==="skipped").length;
  const workspace=$("#workspace"),scroll=workspace.querySelector(".rail")?.scrollLeft||0,historyOpen=workspace.querySelector("details")?.open||false;
  workspace.innerHTML=`<div class="eyebrow">${esc(task.project)} / ${esc(task.task)}</div><div class="heading-row"><h2>${esc(task.title)}</h2>${pill(task.status)}</div><p class="summary">${done} 个阶段已完成${skipped?` · ${skipped} 个已跳过`:""} / 共 ${task.stages.length} 个阶段 · 修订 ${task.revision}</p><nav class="rail" aria-label="流程阶段">${task.stages.map((stage,index)=>`<button type="button" class="stage ${esc(stage.status)} ${stage.id===state.stage?"selected":""}" data-stage="${esc(stage.id)}" aria-pressed="${stage.id===state.stage}"><span class="dot">${stage.status==="completed"?"✓":stage.status==="blocked"?"!":stage.status==="skipped"?"–":index+1}</span><span class="stage-label">${esc(stage.title)}</span><span class="stage-state">${esc(labels[stage.status])}</span></button>`).join("")}</nav><article class="detail"><div class="detail-top"><h3>${esc(selected.title)}</h3>${pill(selected.status)}</div><p class="detail-note">${esc(selected.note||"等待Codex执行并记录这一阶段。")}</p><h4>关联证据</h4>${selected.evidence.length?selected.evidence.map((path,index)=>`<a class="evidence" href="/evidence?task=${encodeURIComponent(task.task)}&stage=${encodeURIComponent(selected.id)}&index=${index}" target="_blank" rel="noopener">${esc(path)}</a>`).join(""):'<p class="nothing">此阶段尚无证据文件</p>'}<div class="record-time">阶段记录：${esc(date(selected.updated_at))}</div></article><details ${historyOpen?"open":""}><summary>查看阶段记录（${task.events.length}）</summary>${task.events.slice().reverse().map(event=>`<div class="event"><time>${esc(date(event.at))}</time><p>${esc(task.stages.find(stage=>stage.id===event.stage)?.title||event.stage)} · ${esc(labels[event.status])} — ${esc(event.note)}</p></div>`).join("")||'<p class="nothing">暂无阶段更新</p>'}</details><p class="record-time">任务最后更新：${esc(date(task.updated_at))} · 这是执行记录，不代表后台进程仍在运行。</p>`;
  workspace.querySelector(".rail").scrollLeft=scroll;
  if(focus){
    const target=focus[0]==="history"?workspace.querySelector("summary"):Array.from(document.querySelectorAll(focus[0]==="href"?".evidence":`[data-${focus[0]}]`)).find(element=>(focus[0]==="href"?element.getAttribute("href"):element.dataset[focus[0]])===focus[1]);
    target?.focus({preventScroll:true});
  }
}

async function refresh(){
  state.controller?.abort();const controller=new AbortController();state.controller=controller;
  const timeout=setTimeout(()=>controller.abort(),5000);
  try{
    const response=await fetch("/api/workflows",{cache:"no-store",signal:controller.signal});
    if(!response.ok)throw new Error(`HTTP ${response.status}`);
    const data=await response.json();if(state.controller!==controller)return;
    const signature=JSON.stringify([data.tasks,data.warnings]);
    state.tasks=data.tasks;state.warnings=data.warnings;
    if(signature!==state.signature){state.signature=signature;render();}
    $("#connection").className=data.warnings.length?"error":"";
    $("#connection").textContent=data.warnings.length?`部分记录无法读取（${data.warnings.map(w=>w.task).join("、")}）；已显示其余任务`:`已连接本地记录 · ${date(data.read_at)} · 页面只读`;
  }catch(error){
    if(state.controller!==controller)return;
    $("#connection").className="error";$("#connection").textContent="连接中断，保留最近读取的记录。请确认看板服务仍在运行，点击刷新重试。";
  }finally{clearTimeout(timeout);if(state.controller===controller)state.controller=null;}
}
document.addEventListener("click",event=>{const task=event.target.closest("[data-task]"),stage=event.target.closest("[data-stage]");if(task){state.task=task.dataset.task;state.stage="";render();}else if(stage){state.stage=stage.dataset.stage;render();}});
$("#search").addEventListener("input",render);$("#filter").addEventListener("change",render);$("#refresh").addEventListener("click",refresh);
document.addEventListener("visibilitychange",()=>{if(!document.hidden)refresh();else{state.controller?.abort();state.controller=null;}});
window.addEventListener("focus",refresh);setInterval(()=>{if(!document.hidden&&!state.controller)refresh();},3000);refresh();
