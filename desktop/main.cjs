'use strict';
const {app,BrowserWindow,ipcMain,nativeImage,shell,screen,session,dialog}=require('electron');
const fs=require('node:fs');
const path=require('node:path');
const http=require('node:http');
const root=path.resolve(__dirname,'..');
const config=JSON.parse(fs.readFileSync(path.join(root,'config.json'),'utf8'));
const origin=`http://127.0.0.1:${config.port}`;
const testMode=process.argv.includes('--self-test');
app.setPath('userData',path.join(root,'data',testMode?'desktop-test-profile':'desktop-profile'));
app.setName('素材台');
let win,compact=false,normalBounds,token;
function localPage(url){try{const u=new URL(url);return u.origin===origin&&u.pathname==='/';}catch{return false;}}
function validCaller(event){return win&&!win.isDestroyed()&&event.sender===win.webContents&&event.senderFrame===win.webContents.mainFrame&&localPage(event.senderFrame.url);}
function assertCaller(event){if(!validCaller(event))throw new Error('不允许的窗口请求');}
function request(endpoint,body){
  return new Promise((resolve,reject)=>{
    const payload=body===undefined?null:JSON.stringify(body);
    const req=http.request(origin+endpoint,{method:payload?'POST':'GET',headers:{...(payload?{'Content-Type':'application/json','Content-Length':Buffer.byteLength(payload)}:{}),'X-Workbench-Token':token||''}},res=>{
      let result='';res.setEncoding('utf8');res.on('data',chunk=>{result+=chunk;if(result.length>4*1024*1024)req.destroy(new Error('响应过大'));});
      res.on('end',()=>{try{const value=JSON.parse(result);if(res.statusCode>=400)throw new Error(typeof value.detail==='string'?value.detail:'请求未完成');resolve(value);}catch(error){reject(error);}});
    });
    req.setTimeout(10000,()=>req.destroy(new Error('本地服务未响应')));req.on('error',reject);req.end(payload);
  });
}
function validatePayload(payload){
  if(!payload||!Array.isArray(payload.asset_ids)||!payload.asset_ids.length||payload.asset_ids.length>30||!payload.asset_ids.every(id=>typeof id==='string'&&/^[a-f0-9]{24}$/.test(id)))throw new Error('无效素材选择');
  const scope=payload.scope==='stack'?'stack':'library';
  if(scope==='stack'&&!/^[a-f0-9]{24}$/.test(payload.project_id||''))throw new Error('无效视频项目');
  return {scope,project_id:payload.project_id||'',asset_ids:[...new Set(payload.asset_ids)]};
}
async function resolveFiles(payload){
  payload=validatePayload(payload);
  token=(await request('/api/bootstrap')).token;
  const endpoint=payload.scope==='stack'?'/api/stack/'+payload.project_id+'/drag':'/api/library/drag';
  const value=await request(endpoint,{asset_ids:payload.asset_ids});
  const videoRoot=fs.realpathSync(config.video_root);
  if(!Array.isArray(value.files)||value.files.length!==payload.asset_ids.length)throw new Error('文件列表不完整');
  return value.files.map(file=>{
    const resolved=fs.realpathSync(file),relative=path.relative(videoRoot,resolved);
    if(relative.startsWith('..'+path.sep)||relative==='..'||path.isAbsolute(relative)||!fs.statSync(resolved).isFile())throw new Error('素材必须是视频目录中的本地文件');
    return resolved;
  });
}
function state(){return {compact,size:win.getSize(),contentSize:win.getContentSize(),alwaysOnTop:win.isAlwaysOnTop(),resizable:win.isResizable()};}
function setCompact(value){
  if(typeof value!=='boolean')throw new Error('无效窗口模式');
  if(value!==compact){
    if(value){
      if(win.isMaximized())win.unmaximize();
      normalBounds=win.getBounds();
      win.setMinimumSize(0,0);win.setMaximumSize(0,0);
      const area=screen.getDisplayMatching(normalBounds).workArea;
      win.setBounds({x:Math.max(area.x,area.x+area.width-440),y:Math.max(area.y,Math.min(normalBounds.y,area.y+area.height-620)),width:420,height:620});
      win.setResizable(false);win.setMaximizable(false);win.setFullScreenable(false);win.setAlwaysOnTop(true);
      win.setSize(420,620);
    }else{
      win.setAlwaysOnTop(false);win.setResizable(true);win.setMaximizable(true);win.setFullScreenable(true);win.setMaximumSize(0,0);win.setMinimumSize(760,560);
      if(normalBounds)win.setBounds(normalBounds);
    }
    compact=value;
  }
  win.webContents.send('desk:state',state());return state();
}
const pixels=Buffer.alloc(32*32*4,255);
for(let y=5;y<27;y++)for(let x=8;x<24;x++)if(x===8||x===23||y===5||y===26||((y===12||y===17||y===22)&&x>11&&x<20)){let i=(y*32+x)*4;pixels[i]=pixels[i+1]=pixels[i+2]=0;}
const dragIcon=nativeImage.createFromBitmap(pixels,{width:32,height:32});
function reportError(event,error){if(validCaller(event))event.sender.send('desk:error',error.message||'操作未完成');}
ipcMain.handle('desk:state',event=>{assertCaller(event);return state();});
ipcMain.handle('desk:compact',(event,value)=>{assertCaller(event);return setCompact(value);});
ipcMain.handle('desk:choose-source',async event=>{
  assertCaller(event);
  const result=await dialog.showOpenDialog(win,{title:'选择要纳入素材库的文件夹',defaultPath:config.video_root,properties:['openDirectory','dontAddToRecent']});
  assertCaller(event);
  return result.canceled||!result.filePaths[0]?'':result.filePaths[0];
});

ipcMain.handle('desk:reveal',async(event,payload)=>{assertCaller(event);const files=await resolveFiles(payload);assertCaller(event);shell.showItemInFolder(files[0]);return true;});
ipcMain.on('desk:drag',async(event,payload)=>{
  try{assertCaller(event);const files=await resolveFiles(payload);assertCaller(event);event.sender.startDrag({files,icon:dragIcon});}
  catch(error){reportError(event,error);}
});
ipcMain.on('desk:close',event=>{if(validCaller(event))win.close();});
ipcMain.on('desk:minimize',event=>{if(validCaller(event))win.minimize();});
function launchArgs(args){return {mini:args.includes('--mini'),project:args.find(a=>a.startsWith('--project='))?.slice(10)||''};}
async function navigateTo(args){
  const parsed=launchArgs(args),boot=await request('/api/bootstrap');token=boot.token;
  const project=boot.projects.find(p=>p.id===parsed.project)?.id||boot.projects[0]?.id||'';
  setCompact(parsed.mini);
  await win.loadURL(`${origin}/?project=${encodeURIComponent(project)}#${parsed.mini?'stack':'library'}`);
}
async function selfTest(){
  const assert=require('node:assert/strict'),results={runtime:process.versions.electron};
  setCompact(true);results.compact=state();
  // Allow the 0–2 DIP Windows non-client border; content dimensions are fixed.
  const actual=win.getSize();assert.ok(actual[0]>=420&&actual[0]<=422&&actual[1]>=620&&actual[1]<=622);
  assert.equal(win.isAlwaysOnTop(),true);assert.equal(win.isResizable(),false);assert.equal(win.isMaximizable(),false);
  results.maximizable=win.isMaximizable();
  setCompact(false);results.normal=state();assert.equal(win.isAlwaysOnTop(),false);assert.equal(win.isResizable(),true);
  assert.equal(localPage('https://example.com/'),false);assert.equal(localPage(origin+'/api/bootstrap'),false);
  assert.throws(()=>validatePayload({project_id:'../',asset_ids:['file:///C:/secret']}));
  const boot=await request('/api/bootstrap');
  for(const project of boot.projects){const stack=await request(`/api/stack/${project.id}`);const available=stack.items.filter(i=>i.available);if(available.length){const files=await resolveFiles({project_id:project.id,asset_ids:[available[0].asset_id]});results.localFileValidated=files[0];break;}}
  results.nativeDragRegistered=true;results.editorDropVerified=false;results.passed=true;
  fs.writeFileSync(path.join(root,'桌面窗口验证.json'),JSON.stringify(results,null,2));app.quit();
}
if(!app.requestSingleInstanceLock()){app.quit();}else{
  app.on('second-instance',(_event,args)=>{if(win)navigateTo(args).then(()=>{if(win.isMinimized())win.restore();win.show();win.focus();}).catch(error=>win.webContents.send('desk:error',error.message));});
  app.whenReady().then(async()=>{
    session.defaultSession.setPermissionRequestHandler((_wc,_permission,callback)=>callback(false));
    session.defaultSession.setPermissionCheckHandler(()=>false);
    win=new BrowserWindow({width:1220,height:820,minWidth:760,minHeight:560,show:false,frame:false,thickFrame:false,backgroundColor:'#ffffff',title:'素材台',webPreferences:{preload:path.join(__dirname,'preload.cjs'),contextIsolation:true,sandbox:true,nodeIntegration:false,webSecurity:true,webviewTag:false}});
    win.setMenu(null);
    win.webContents.on('will-navigate',(event,url)=>{if(!localPage(url))event.preventDefault();});
    win.webContents.setWindowOpenHandler(({url})=>{if(url==='https://music.gdstudio.org/')shell.openExternal(url);return {action:'deny'};});
    win.webContents.on('will-attach-webview',event=>event.preventDefault());
    win.webContents.on('did-finish-load',()=>win.webContents.send('desk:state',state()));
    win.on('closed',()=>{win=null;});
    await navigateTo(process.argv);
    if(testMode)await selfTest();else win.show();
  }).catch(error=>{fs.writeFileSync(path.join(root,'data','desktop-error.log'),error.stack||String(error));app.exit(1);});
  app.on('window-all-closed',()=>app.quit());
}
