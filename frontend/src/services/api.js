const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';
export const token = { get:()=>sessionStorage.getItem('hb_token'), set:(v,r)=>{sessionStorage.setItem('hb_token',v);if(r)sessionStorage.setItem('hb_refresh',r)}, clear:()=>{sessionStorage.removeItem('hb_token');sessionStorage.removeItem('hb_refresh')} };
export async function api(path, options={}) {
  const send=()=>fetch(`${BASE}${path}`,{...options,headers:{...(options.body && !(options.body instanceof FormData)?{'Content-Type':'application/json'}:{}),...(token.get()?{Authorization:`Bearer ${token.get()}`}:{}) ,...options.headers}});
  let res=await send();
  if(res.status===401 && token.get() && !path.includes('/auth/refresh') && sessionStorage.getItem('hb_refresh')){
    const refresh=await fetch(`${BASE}/api/auth/refresh`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({refresh_token:sessionStorage.getItem('hb_refresh')})});
    if(refresh.ok){const renewed=await refresh.json();token.set(renewed.access_token,renewed.refresh_token);res=await send()}else token.clear();
  }
  if(!res.ok){let detail=`Request failed (${res.status})`;try{const payload=await res.json();const value=payload?.detail??payload?.message;if(typeof value==='string')detail=value;else if(Array.isArray(value))detail=value.map(item=>item?.msg||JSON.stringify(item)).join('. ');else if(value&&typeof value==='object')detail=value.message||value.msg||JSON.stringify(value)}catch{};throw new Error(detail)}
  if(res.status===204)return null;return res.json();
}
export const imageUrl=url=>url?.startsWith('http')?url:`${BASE}${url||''}`;
