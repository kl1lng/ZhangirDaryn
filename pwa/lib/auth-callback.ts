type CallbackAuth={
 getSession:()=>Promise<{data:{session:unknown};error:unknown}>;
 exchangeCodeForSession:(code:string)=>Promise<{error:unknown}>;
};

export async function completeSupabaseCallback(auth:CallbackAuth,code:string|null){
 // getSession waits for SDK initialization, including automatic PKCE exchange.
 const current=await auth.getSession();
 if(current.error)throw current.error;
 if(current.data.session)return;
 if(!code)throw new Error('No authenticated session.');
 const result=await auth.exchangeCodeForSession(code);
 if(result.error)throw result.error;
}
