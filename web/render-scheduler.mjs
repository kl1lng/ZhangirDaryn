export function createRenderScheduler({requestFrame,cancelFrame,render}){
  let frame=null,visible=true,disposed=false;
  function invalidate(){
    if(disposed||!visible||frame!==null)return;
    frame=requestFrame(()=>{
      frame=null;
      if(!disposed&&visible)render();
    });
  }
  function setVisible(next){
    visible=Boolean(next);
    if(!visible&&frame!==null){cancelFrame(frame);frame=null}
    if(visible)invalidate();
  }
  function dispose(){
    disposed=true;
    if(frame!==null){cancelFrame(frame);frame=null}
  }
  return {invalidate,setVisible,dispose};
}
