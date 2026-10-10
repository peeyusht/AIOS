/* Cleanup page, injected into the built bundle (same scope as the other pages).
   Uses the bundle's own helpers: f (jsx runtime), Z (React), uc (Button), al (Panel), Ba (Badge),
   Yn (error), Gf (empty state), He (bytes), cc (date), Wl (GET), cm (POST), Qt (icon factory). */
const SFtrash=Qt("trash-2",[["path",{d:"M3 6h18",key:"t1"}],["path",{d:"M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6",key:"t2"}],["path",{d:"M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2",key:"t3"}],["line",{x1:"10",x2:"10",y1:"11",y2:"17",key:"t4"}],["line",{x1:"14",x2:"14",y1:"11",y2:"17",key:"t5"}]]);
const SFlevels=[["safe","Safe to delete","success"],["likely","Probably safe","info"],["review","Review","warning"],["keep","Keep / archive","muted"]];
const SFcat={duplicate_of_filed:"Duplicate of a filed copy",duplicate_in_downloads:"Duplicate in Downloads",partial_download:"Partial download",archive_extracted:"Archive already extracted",installer:"Installer",driver_package:"Driver package",executable:"Program",old_unopened:"Old, not opened",firmware_or_image:"Firmware / image"};
function SFx(t,p,...c){return c.length>1?f.jsxs(t,{...p,children:c}):f.jsx(t,{...p,children:c[0]})}
function SFcleanup(){
  const[flt,setFlt]=Z.useState("all"),[q,setQ]=Z.useState(""),[hide,setHide]=Z.useState(!0),[msg,setMsg]=Z.useState(null),[busy,setBusy]=Z.useState(null);
  const[fast,setFast]=Z.useState(!1);
  const{data:d,error:err,reload}=Ya(()=>Wl("/api/cleanup"),fast?2e3:15e3,[fast]);
  const running=!!d?.runner?.running, deleting=!!d?.deleter?.running;
  Z.useEffect(()=>{setFast(running||deleting)},[running,deleting]);
  const[ask,setAsk]=Z.useState(null),[ack,setAck]=Z.useState(!1);
  const pl=d?.plan, dres=d?.deleter?.result;
  const runDelete=async mode=>{setFast(!0);setAsk(null);setAck(!1);
    await post("/api/cleanup/delete",mode==="recycle"?{mode}:{mode,paths:pl.too_big.map(x=>x.path),confirm:"DELETE PERMANENTLY"},"del")};
  const tooBigBytes=(pl?.too_big??[]).reduce((a,x)=>a+x.size,0);
  const lim=pl?.limits?Object.values(pl.limits)[0]:null;
  const rep=d?.report;
  const post=async(url,body,key)=>{setBusy(key);setMsg(null);try{const r=await cm(url,body);if(r&&r.ok===!1)setMsg(r.message);await reload()}catch(e){setMsg(e instanceof Error?e.message:String(e))}setBusy(null)};
  const scan=()=>{setFast(!0);post("/api/cleanup/scan",{},"scan")};
  const decide=(it,v)=>post("/api/cleanup/decision",{path:it.path,decision:it.decision===v?null:v},it.path+v);
  const reveal=it=>post("/api/cleanup/reveal",{path:it.path},it.path+"show");
  const items=(rep?.items??[]).filter(it=>(flt==="all"||it.level===flt)&&(!hide||!it.decision||it.decision==="agree")&&(!q||(it.path+" "+it.reason).toLowerCase().includes(q.toLowerCase())));
  const hiddenN=(rep?.items??[]).filter(it=>it.decision==="keep"||it.decision==="disagree").length;
  const agreed=(rep?.items??[]).filter(it=>it.decision==="agree"&&it.level!=="keep");
  const agreedBytes=agreed.reduce((a,it)=>a+it.size,0);
  const cnt=rep?.counts;
  return SFx("div",{className:"space-y-4"},
    SFx("div",{className:"flex flex-wrap items-center gap-3"},
      SFx("h1",{className:"text-lg font-semibold"},"Cleanup"),
      SFx("span",{className:"text-xs text-muted-foreground","aria-live":"polite"},
        running?`Scanning… ${d.runner.progress??""}`:rep?`Last scan ${cc(rep.scanned_at)} · ${cnt.inbox_files} files in Downloads compared with ${cnt.para_files} in your PARA tree · ${rep.seconds}s`:d?"No scan yet":"Loading…"),
      SFx("div",{className:"ml-auto flex flex-wrap items-center gap-2"},
        rep&&SFx("a",{href:"/api/cleanup.csv",className:"inline-flex items-center gap-1.5 rounded-md border bg-card px-3 py-1.5 text-sm font-medium hover:bg-accent"},"Export CSV"),
        SFx(uc,{variant:"primary",onClick:scan,disabled:running||busy==="scan"},SFx(d1,{className:`h-4 w-4 ${running?"animate-spin":""}`}),running?"Scanning":"Scan now"))),
    SFx("div",{className:"flex items-start gap-2 rounded-md border border-info bg-info-soft px-3 py-2 text-sm text-info"},SFx(u1,{className:"mt-0.5 h-4 w-4 shrink-0"}),
      SFx("span",null,"Nothing is deleted until you mark it ",SFx("b",null,"Agree")," and then confirm below. Each file is checked again right before deleting; anything that changed is skipped. ",SFx("b",null,"Show")," opens the file in Explorer. ",SFx("b",null,"Disagree")," teaches us which rules to trust.")),
    err&&f.jsx(Yn,{error:err}),
    msg&&SFx("div",{role:"alert",className:"rounded-md border border-warning bg-warning-soft px-3 py-2 text-sm text-warning"},msg),
    d?.runner?.error&&SFx("div",{role:"alert",className:"rounded-md border border-danger bg-danger-soft px-3 py-2 text-sm text-danger"},"Last scan failed: ",d.runner.error),
    !rep&&d&&!running&&f.jsx(Gf,{title:"No scan yet",children:"Click Scan now. It reads names and sizes, and opens only files that have a same-size twin."}),
    rep&&SFx("div",{className:"grid gap-3",style:{gridTemplateColumns:"repeat(auto-fit,minmax(170px,1fr))"}},
      SFlevels.map(([k,label,tone])=>{const b=rep.by_level[k]??{count:0,bytes:0};return SFx("button",{key:k,onClick:()=>setFlt(flt===k?"all":k),"aria-pressed":flt===k,className:`panel px-4 py-3 text-left hover:bg-accent ${flt===k?"bg-accent":""}`},
        SFx("div",{className:"flex items-center gap-2"},f.jsx(Ba,{tone,children:label})),
        SFx("div",{className:"mt-2 text-2xl font-semibold"},He(b.bytes)),
        SFx("div",{className:"text-xs text-muted-foreground"},`${b.count} item${b.count===1?"":"s"}`))}),
      SFx("div",{className:"panel px-4 py-3"},
        SFx("div",{className:"text-xs font-medium text-muted-foreground"},"You agreed to delete"),
        SFx("div",{className:"mt-2 text-2xl font-semibold"},He(agreedBytes)),
        SFx("div",{className:"text-xs text-muted-foreground"},`${agreed.length} item${agreed.length===1?"":"s"}`))),
    rep&&(agreed.length>0||deleting||dres)&&f.jsx(al,{title:"Delete agreed files",children:SFx("div",{className:"space-y-3 text-sm"},
      deleting&&SFx("div",{className:"flex items-center gap-2"},SFx(d1,{className:"h-4 w-4 animate-spin"}),"Deleting… ",d.deleter.progress??""),
      d?.deleter?.error&&SFx("div",{className:"text-danger"},"Delete failed: ",d.deleter.error),
      !deleting&&pl&&pl.recycle_count>0&&SFx("div",{className:"flex flex-wrap items-center gap-3"},
        SFx("span",null,SFx("b",null,`${pl.recycle_count} file${pl.recycle_count===1?"":"s"} · ${He(pl.recycle_bytes)}`)," can go to the Recycle Bin (restorable)."),
        ask==="recycle"?SFx("span",{className:"flex items-center gap-2"},"Move them now?",
            SFx(uc,{variant:"primary",onClick:()=>runDelete("recycle")},"Yes, move to Recycle Bin"),SFx(uc,{onClick:()=>setAsk(null)},"Cancel")):
          SFx(uc,{variant:"primary",onClick:()=>setAsk("recycle"),disabled:running},f.jsx(SFtrash,{className:"h-4 w-4"}),"Move to Recycle Bin")),
      !deleting&&pl&&pl.recycle_count>0&&SFx("p",{className:"text-xs text-muted-foreground"},"The Recycle Bin keeps using the disk space until you empty it."),
      !deleting&&pl?.too_big?.length>0&&SFx("div",{className:"rounded-md border border-warning bg-warning-soft p-3 text-warning"},
        SFx("div",null,SFx("b",null,`${pl.too_big.length} file${pl.too_big.length===1?"":"s"} · ${He(tooBigBytes)}`),` ${pl.too_big.length===1?"is":"are"} too big for the Recycle Bin`,lim?.max_bytes?` on ${lim.drive??"this drive"} (limit about ${He(lim.max_bytes)}${lim.known?"":", estimated"})`:"",". Windows would delete ",pl.too_big.length===1?"it":"them"," permanently, so ",pl.too_big.length===1?"it is":"they are"," not included above."),
        SFx("ul",{className:"mt-2 space-y-0.5 font-mono text-xs"},pl.too_big.map(x=>SFx("li",{key:x.path,className:"truncate",title:x.path},He(x.size)," · ",x.name))),
        ask==="permanent"?SFx("div",{className:"mt-3 space-y-2"},
            SFx("label",{className:"flex items-center gap-2"},f.jsx("input",{type:"checkbox",checked:ack,onChange:e=>setAck(e.target.checked)}),"I understand these cannot be restored."),
            SFx("div",{className:"flex gap-2"},SFx(uc,{variant:"danger",disabled:!ack,onClick:()=>runDelete("permanent")},`Delete ${pl.too_big.length} permanently`),SFx(uc,{onClick:()=>{setAsk(null);setAck(!1)}},"Cancel"))):
          SFx("div",{className:"mt-3"},SFx(uc,{variant:"danger",onClick:()=>setAsk("permanent"),disabled:running},"Delete permanently…"))),
      !deleting&&pl&&pl.recycle_count===0&&!(pl.too_big?.length)&&agreed.length>0&&SFx("p",{className:"text-muted-foreground"},"None of the agreed files can be deleted from here (Keep / archive items are excluded)."),
      dres&&!deleting&&SFx("div",{className:"rounded-md border p-3"},
        SFx("div",{className:"float-right"},SFx(uc,{onClick:()=>post("/api/cleanup/recyclebin",{},"bin")},"Open Recycle Bin")),
        SFx("div",null,SFx("b",null,"Last run"),` (${dres.mode==="recycle"?"Recycle Bin":"permanent"}, ${cc(dres.finished)}): deleted ${dres.deleted.length} file${dres.deleted.length===1?"":"s"}, ${He(dres.deleted_bytes)}`,dres.skipped.length?`; skipped ${dres.skipped.length}`:"",dres.failed.length?`; failed ${dres.failed.length}`:"","."),
        [...dres.deleted.filter(x=>x.why).map(x=>["Check",x]),...dres.skipped.map(x=>["Skipped",x]),...dres.failed.map(x=>["Failed",x])].length>0&&SFx("ul",{className:"mt-2 space-y-1 text-xs"},
          [...dres.deleted.filter(x=>x.why).map(x=>["Check",x]),...dres.skipped.map(x=>["Skipped",x]),...dres.failed.map(x=>["Failed",x])].map(([k,x])=>SFx("li",{key:k+x.path},SFx("b",null,k,": "),x.name," — ",x.why)))))}),
    rep&&SFx("div",{className:"flex flex-wrap items-center gap-3"},
      SFx("div",{role:"tablist","aria-label":"Filter",className:"flex flex-wrap rounded-md border bg-card p-0.5"},
        [["all","All"],...SFlevels.map(([k,l])=>[k,l])].map(([k,l])=>f.jsx("button",{role:"tab","aria-selected":flt===k,onClick:()=>setFlt(k),className:`rounded-sm px-2.5 py-1 text-sm ${flt===k?"bg-accent font-medium":"text-muted-foreground hover:text-foreground"}`,children:l},k))),
      SFx("label",{className:"flex items-center gap-2 text-sm text-muted-foreground"},f.jsx("input",{type:"checkbox",checked:hide,onChange:e=>setHide(e.target.checked)}),`Hide ones I marked Keep or Disagree${hiddenN?` (${hiddenN})`:""}`),
      SFx("label",{className:"relative ml-auto"},SFx("span",{className:"sr-only"},"Search"),f.jsx(g1,{className:"pointer-events-none absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"}),
        f.jsx("input",{value:q,onChange:e=>setQ(e.target.value),placeholder:"Search name, folder, reason…",className:"w-64 rounded-md border bg-card py-1.5 pl-8 pr-2 text-sm"}))),
    rep&&items.length===0&&f.jsx(Gf,{title:rep.items.length?"Nothing matches this filter":"Nothing to clean up",children:rep.items.length?null:"No duplicates, old installers or leftovers found."}),
    rep&&items.length>0&&SFx("div",{className:"panel overflow-x-auto"},
      SFx("table",{className:"w-full text-sm",style:{minWidth:"940px"}},
        SFx("thead",{className:"border-b bg-muted text-left text-xs text-muted-foreground"},
          SFx("tr",null,["File","Size","Added","Last opened","Recommendation","Why","" ].map((h,i)=>f.jsx("th",{className:"px-3 py-2 font-medium",children:h},i)))),
        f.jsx("tbody",{children:items.map(it=>{const lv=SFlevels.find(l=>l[0]===it.level)??["info","Info","muted"];return SFx("tr",{key:it.path,className:"border-t align-top hover:bg-muted",style:it.decision==="agree"?{opacity:.6}:null},
          SFx("td",{className:"px-3 py-2",style:{maxWidth:"230px"}},SFx("div",{className:"truncate font-medium",title:it.path},it.is_dir?"📁 ":"",it.name),SFx("div",{className:"truncate text-xs text-muted-foreground",title:it.folder},it.folder)),
          SFx("td",{className:"whitespace-nowrap px-3 py-2"},He(it.size)),
          SFx("td",{className:"whitespace-nowrap px-3 py-2 text-muted-foreground",title:it.added},it.age_days==null?"–":`${it.age_days} d ago`),
          SFx("td",{className:"whitespace-nowrap px-3 py-2 text-muted-foreground",title:it.last_opened??"No Recent Items entry"},it.last_opened?cc(it.last_opened):"no record"),
          SFx("td",{className:"px-3 py-2"},f.jsx(Ba,{tone:lv[2],children:lv[1]}),SFx("div",{className:"mt-1 text-xs text-muted-foreground"},SFcat[it.category]??it.category)),
          SFx("td",{className:"px-3 py-2 text-muted-foreground",style:{maxWidth:"330px"}},SFx("div",null,it.reason),
            it.related&&SFx("div",{className:"mt-1 truncate font-mono text-xs",title:it.related},"Same as: ",it.related),
            it.caution&&SFx("div",{className:"mt-1 text-xs text-warning"},"⚠ ",it.caution)),
          SFx("td",{className:"px-3 py-2",style:{width:"1%"}},SFx("div",{className:"flex gap-1"},
            f.jsx("button",{onClick:()=>reveal(it),disabled:busy===it.path+"show",title:"Open Explorer with this file selected",className:"rounded-md border bg-card px-2 py-1 text-xs hover:bg-accent",children:"Show"}),
            it.level!=="keep"&&f.jsx("button",{onClick:()=>decide(it,"agree"),"aria-pressed":it.decision==="agree",title:"I agree this can be deleted",className:`rounded-md border px-2 py-1 text-xs ${it.decision==="agree"?"bg-success-soft text-success":"bg-card hover:bg-accent"}`,children:"Agree"}),
            f.jsx("button",{onClick:()=>decide(it,it.level==="keep"?"keep":"disagree"),"aria-pressed":it.decision==="disagree"||it.decision==="keep",title:"Wrong recommendation; hide it",className:`rounded-md border px-2 py-1 text-xs ${it.decision==="disagree"||it.decision==="keep"?"bg-danger-soft text-danger":"bg-card hover:bg-accent"}`,children:it.level==="keep"?"Keep":"Disagree"}))))})}))),
    rep&&f.jsx(al,{title:"How this scan worked",children:f.jsx(Cf,{rows:[
      ["Compared","Content (SHA-256), not names. Files are opened only when another file has exactly the same size; zero-byte files and hard links are skipped."],
      ["Cloud-only files",cnt.cloud_only_para?`${cnt.cloud_only_para} PARA file(s) are online-only and were not opened (no downloads triggered)${cnt.unconfirmed_cloud_groups?`; ${cnt.unconfirmed_cloud_groups} Downloads file(s) have a same-size online-only twin that can't be confirmed`:""}.`:"None found; everything was compared locally."],
      ["Files hashed",String(cnt.files_hashed)],
      ["Last opened","From Windows Recent Items (matched by name, so it's a hint). "+(rep.recent_items_found?`${rep.recent_items_found} entries found.`:"No entries found.")],
      ["NTFS last-access",`${rep.last_access?.text??"unknown"}. Not used for decisions: background readers (indexing, antivirus, this agent) update it too.`],
      ["Thresholds",`installers and programs ${rep.settings.installer_days} d · drivers ${rep.settings.driver_days} d · other files ${rep.settings.stale_days} d (documents never on age alone)`],
      ...(rep.errors?.length?[["Warnings",rep.errors.join("; ")]]:[])]})}),
    rep?.para_duplicates?.length>0&&f.jsx(al,{title:`Duplicates inside your PARA tree (${rep.para_duplicates.length}, information only)`,children:
      SFx("ul",{className:"space-y-2 text-sm"},rep.para_duplicates.slice(0,50).map((g,i)=>SFx("li",{key:i,className:"rounded-md border",style:{padding:"8px 10px"}},
        SFx("div",{className:"text-xs text-muted-foreground"},He(g.size)," each",g.confirmed?"":" · sampled, not fully confirmed"),
        g.paths.map(p=>f.jsx("div",{className:"truncate font-mono text-xs",title:p,children:p},p)))))}));
}
