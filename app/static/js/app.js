(function(){
  const panel=document.querySelector("[data-status-url]");
  if(!panel)return;

  const statusUrl=panel.dataset.statusUrl;
  const terminal=new Set(["succeeded","failed","cancelled","rejected"]);
  const active=new Set(["approved","queued","running"]);
  const statusIntervalMs=4000;
  const outputIntervalMs=8000;
  let currentStatus=panel.dataset.currentStatus||"";
  let hasForemanJob=panel.dataset.hasForemanJob==="true";
  let statusTimer=null;
  let outputTimer=null;
  let outputLoading=false;

  const statusPill=document.getElementById("request-status");
  const foremanJob=document.getElementById("foreman-job");
  const executionState=document.getElementById("execution-state");
  const lastPolled=document.getElementById("last-polled");
  const refreshState=document.getElementById("execution-refresh-state");
  const errorBox=document.getElementById("execution-error");
  const outputButton=document.getElementById("load-output");
  const outputSection=document.getElementById("output-section");
  const outputPlaceholder=document.getElementById("output-placeholder");
  const outputBox=document.getElementById("job-output");
  const outputRefreshState=document.getElementById("output-refresh-state");
  const outputLastRefreshed=document.getElementById("output-last-refreshed");
  const copyButton=document.getElementById("copy-output");
  const fullscreenButton=document.getElementById("toggle-execution-fullscreen");

  function textStatus(value){
    return (value||"").replaceAll("_"," ");
  }

  function setStep(name,state){
    const el=document.querySelector(`[data-step="${name}"]`);
    if(!el)return;
    el.classList.remove("done","active","failed");
    if(state)el.classList.add(state);
  }

  function updateSteps(status,foremanId){
    setStep("submitted","done");
    setStep("approved",["approved","queued","running","succeeded","failed","cancelled"].includes(status)?"done":status==="rejected"?"failed":"");
    setStep("foreman",foremanId?"done":"");

    if(status==="running")setStep("ansible","active");
    else if(status==="succeeded")setStep("ansible","done");
    else if(status==="failed"||status==="cancelled")setStep("ansible","failed");
    else setStep("ansible","");

    if(status==="succeeded")setStep("completed","done");
    else if(status==="failed"||status==="cancelled"||status==="rejected")setStep("completed","failed");
    else setStep("completed","");
  }

  function updateStatusUI(d){
    currentStatus=d.status||currentStatus;
    hasForemanJob=Boolean(d.foreman_job_id);
    panel.dataset.currentStatus=currentStatus;
    panel.dataset.hasForemanJob=hasForemanJob?"true":"false";

    if(statusPill){
      statusPill.textContent=textStatus(currentStatus);
      statusPill.className="status "+currentStatus;
    }
    if(foremanJob)foremanJob.textContent=d.foreman_job_id||"Waiting to submit";
    if(outputSection)outputSection.hidden=!hasForemanJob;
    if(outputPlaceholder)outputPlaceholder.hidden=hasForemanJob;
    if(executionState)executionState.textContent=d.status_label||currentStatus;
    if(lastPolled)lastPolled.textContent=d.last_polled_at||"Not yet polled";
    if(errorBox){
      if(d.error){errorBox.hidden=false;errorBox.textContent=d.error;}
      else{errorBox.hidden=true;errorBox.textContent="";}
    }
    updateSteps(currentStatus,d.foreman_job_id);

    if(refreshState){
      refreshState.textContent=terminal.has(currentStatus)
        ? "Execution has reached a terminal state; live status refresh is paused."
        : "Live status refresh is active (every 4 seconds).";
    }
    if(outputRefreshState){
      outputRefreshState.textContent=active.has(currentStatus)&&hasForemanJob
        ? "Auto-refreshing every 8 seconds"
        : terminal.has(currentStatus)?"Final output":"Waiting for execution";
    }
  }

  async function loadOutput(automatic=false){
    if(!outputButton||!outputBox||outputLoading)return;
    outputLoading=true;
    if(!automatic){
      outputButton.disabled=true;
      outputButton.textContent="Refreshing…";
    }
    const nearBottom=(outputBox.scrollHeight-outputBox.scrollTop-outputBox.clientHeight)<80;
    try{
      const r=await fetch(outputButton.dataset.outputUrl,{headers:{Accept:"application/json"},cache:"no-store"});
      if(!r.ok)throw new Error(`HTTP ${r.status}`);
      const d=await r.json();
      const rendered=d.ready
        ? d.outputs.map(x=>`=== ${x.host}${x.status?" ["+x.status+"]":""} ===\n${typeof x.output==="string"?x.output:JSON.stringify(x.output,null,2)}`).join("\n\n")
        : "Output is not available yet.";
      outputBox.textContent=rendered;
      if(nearBottom)outputBox.scrollTop=outputBox.scrollHeight;
      if(outputLastRefreshed)outputLastRefreshed.textContent=`Updated ${new Date().toLocaleTimeString()}`;
    }catch(e){
      if(!automatic)outputBox.textContent="Unable to retrieve Foreman output.";
      if(outputLastRefreshed)outputLastRefreshed.textContent="Last refresh failed";
    }finally{
      outputLoading=false;
      if(!automatic){
        outputButton.disabled=false;
        outputButton.textContent="Refresh now";
      }
    }
  }

  function scheduleOutput(){
    clearTimeout(outputTimer);
    if(!outputButton||!hasForemanJob)return;
    if(active.has(currentStatus)){
      outputTimer=setTimeout(async()=>{
        await loadOutput(true);
        scheduleOutput();
      },outputIntervalMs);
    }
  }

  async function pollStatus(){
    try{
      const r=await fetch(statusUrl,{headers:{"Accept":"application/json"},cache:"no-store"});
      if(!r.ok)throw new Error(`HTTP ${r.status}`);
      const d=await r.json();
      const previousStatus=currentStatus;
      const previousHasJob=hasForemanJob;
      updateStatusUI(d);

      if(outputButton&&hasForemanJob&&(!previousHasJob||previousStatus!==currentStatus||terminal.has(currentStatus))){
        await loadOutput(true);
      }
      scheduleOutput();

      clearTimeout(statusTimer);
      if(!terminal.has(currentStatus))statusTimer=setTimeout(pollStatus,statusIntervalMs);
    }catch(e){
      if(refreshState)refreshState.textContent="Live refresh temporarily unavailable; retrying…";
      clearTimeout(statusTimer);
      statusTimer=setTimeout(pollStatus,10000);
    }
  }

  if(outputButton){
    outputButton.addEventListener("click",()=>loadOutput(false));
    if(hasForemanJob)loadOutput(true);
  }

  if(copyButton&&outputBox){
    copyButton.addEventListener("click",async()=>{
      try{
        await navigator.clipboard.writeText(outputBox.textContent||"");
        const original=copyButton.textContent;
        copyButton.textContent="Copied";
        setTimeout(()=>{copyButton.textContent=original;},1200);
      }catch(e){
        copyButton.textContent="Copy failed";
        setTimeout(()=>{copyButton.textContent="Copy";},1200);
      }
    });
  }

  if(fullscreenButton){
    fullscreenButton.addEventListener("click",()=>{
      const enabled=panel.classList.toggle("fullscreen");
      document.body.classList.toggle("execution-fullscreen-open",enabled);
      fullscreenButton.textContent=enabled?"Exit full screen":"Full screen";
      if(enabled&&outputBox)outputBox.focus();
    });
  }

  updateSteps(currentStatus,hasForemanJob);
  scheduleOutput();
  statusTimer=setTimeout(pollStatus,1000);
})();
