const {contextBridge,ipcRenderer,webUtils}=require('electron');
contextBridge.exposeInMainWorld('mediaDesk',{
  getState:()=>ipcRenderer.invoke('desk:state'),
  setCompact:value=>ipcRenderer.invoke('desk:compact',value),
  startDrag:payload=>ipcRenderer.send('desk:drag',payload),
  chooseSource:()=>ipcRenderer.invoke('desk:choose-source'),
  reveal:payload=>ipcRenderer.invoke('desk:reveal',payload),
  minimize:()=>ipcRenderer.send('desk:minimize'),
  close:()=>ipcRenderer.send('desk:close'),
  pathForFile:file=>webUtils.getPathForFile(file),
  onState:callback=>{ipcRenderer.on('desk:state',(_event,value)=>callback(value));},
  onError:callback=>{ipcRenderer.on('desk:error',(_event,message)=>callback(message));}
});
