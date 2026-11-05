const t=globalThis,e=t.ShadowRoot&&(void 0===t.ShadyCSS||t.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,s=Symbol(),i=new WeakMap;let r=class{constructor(t,e,i){if(this._$cssResult$=!0,i!==s)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=t,this.t=e}get styleSheet(){let t=this.o;const s=this.t;if(e&&void 0===t){const e=void 0!==s&&1===s.length;e&&(t=i.get(s)),void 0===t&&((this.o=t=new CSSStyleSheet).replaceSync(this.cssText),e&&i.set(s,t))}return t}toString(){return this.cssText}};const a=(t,...e)=>{const i=1===t.length?t[0]:e.reduce((e,s,i)=>e+(t=>{if(!0===t._$cssResult$)return t.cssText;if("number"==typeof t)return t;throw Error("Value passed to 'css' function must be a 'css' function result: "+t+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(s)+t[i+1],t[0]);return new r(i,t,s)},n=e?t=>t:t=>t instanceof CSSStyleSheet?(t=>{let e="";for(const s of t.cssRules)e+=s.cssText;return(t=>new r("string"==typeof t?t:t+"",void 0,s))(e)})(t):t,{is:o,defineProperty:l,getOwnPropertyDescriptor:c,getOwnPropertyNames:d,getOwnPropertySymbols:p,getPrototypeOf:_}=Object,h=globalThis,u=h.trustedTypes,g=u?u.emptyScript:"",m=h.reactiveElementPolyfillSupport,f=(t,e)=>t,y={toAttribute(t,e){switch(e){case Boolean:t=t?g:null;break;case Object:case Array:t=null==t?t:JSON.stringify(t)}return t},fromAttribute(t,e){let s=t;switch(e){case Boolean:s=null!==t;break;case Number:s=null===t?null:Number(t);break;case Object:case Array:try{s=JSON.parse(t)}catch(t){s=null}}return s}},v=(t,e)=>!o(t,e),b={attribute:!0,type:String,converter:y,reflect:!1,useDefault:!1,hasChanged:v};Symbol.metadata??=Symbol("metadata"),h.litPropertyMetadata??=new WeakMap;let x=class extends HTMLElement{static addInitializer(t){this._$Ei(),(this.l??=[]).push(t)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(t,e=b){if(e.state&&(e.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(t)&&((e=Object.create(e)).wrapped=!0),this.elementProperties.set(t,e),!e.noAccessor){const s=Symbol(),i=this.getPropertyDescriptor(t,s,e);void 0!==i&&l(this.prototype,t,i)}}static getPropertyDescriptor(t,e,s){const{get:i,set:r}=c(this.prototype,t)??{get(){return this[e]},set(t){this[e]=t}};return{get:i,set(e){const a=i?.call(this);r?.call(this,e),this.requestUpdate(t,a,s)},configurable:!0,enumerable:!0}}static getPropertyOptions(t){return this.elementProperties.get(t)??b}static _$Ei(){if(this.hasOwnProperty(f("elementProperties")))return;const t=_(this);t.finalize(),void 0!==t.l&&(this.l=[...t.l]),this.elementProperties=new Map(t.elementProperties)}static finalize(){if(this.hasOwnProperty(f("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(f("properties"))){const t=this.properties,e=[...d(t),...p(t)];for(const s of e)this.createProperty(s,t[s])}const t=this[Symbol.metadata];if(null!==t){const e=litPropertyMetadata.get(t);if(void 0!==e)for(const[t,s]of e)this.elementProperties.set(t,s)}this._$Eh=new Map;for(const[t,e]of this.elementProperties){const s=this._$Eu(t,e);void 0!==s&&this._$Eh.set(s,t)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(t){const e=[];if(Array.isArray(t)){const s=new Set(t.flat(1/0).reverse());for(const t of s)e.unshift(n(t))}else void 0!==t&&e.push(n(t));return e}static _$Eu(t,e){const s=e.attribute;return!1===s?void 0:"string"==typeof s?s:"string"==typeof t?t.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(t=>this.enableUpdating=t),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(t=>t(this))}addController(t){(this._$EO??=new Set).add(t),void 0!==this.renderRoot&&this.isConnected&&t.hostConnected?.()}removeController(t){this._$EO?.delete(t)}_$E_(){const t=new Map,e=this.constructor.elementProperties;for(const s of e.keys())this.hasOwnProperty(s)&&(t.set(s,this[s]),delete this[s]);t.size>0&&(this._$Ep=t)}createRenderRoot(){const s=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return((s,i)=>{if(e)s.adoptedStyleSheets=i.map(t=>t instanceof CSSStyleSheet?t:t.styleSheet);else for(const e of i){const i=document.createElement("style"),r=t.litNonce;void 0!==r&&i.setAttribute("nonce",r),i.textContent=e.cssText,s.appendChild(i)}})(s,this.constructor.elementStyles),s}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(t=>t.hostConnected?.())}enableUpdating(t){}disconnectedCallback(){this._$EO?.forEach(t=>t.hostDisconnected?.())}attributeChangedCallback(t,e,s){this._$AK(t,s)}_$ET(t,e){const s=this.constructor.elementProperties.get(t),i=this.constructor._$Eu(t,s);if(void 0!==i&&!0===s.reflect){const r=(void 0!==s.converter?.toAttribute?s.converter:y).toAttribute(e,s.type);this._$Em=t,null==r?this.removeAttribute(i):this.setAttribute(i,r),this._$Em=null}}_$AK(t,e){const s=this.constructor,i=s._$Eh.get(t);if(void 0!==i&&this._$Em!==i){const t=s.getPropertyOptions(i),r="function"==typeof t.converter?{fromAttribute:t.converter}:void 0!==t.converter?.fromAttribute?t.converter:y;this._$Em=i;const a=r.fromAttribute(e,t.type);this[i]=a??this._$Ej?.get(i)??a,this._$Em=null}}requestUpdate(t,e,s,i=!1,r){if(void 0!==t){const a=this.constructor;if(!1===i&&(r=this[t]),s??=a.getPropertyOptions(t),!((s.hasChanged??v)(r,e)||s.useDefault&&s.reflect&&r===this._$Ej?.get(t)&&!this.hasAttribute(a._$Eu(t,s))))return;this.C(t,e,s)}!1===this.isUpdatePending&&(this._$ES=this._$EP())}C(t,e,{useDefault:s,reflect:i,wrapped:r},a){s&&!(this._$Ej??=new Map).has(t)&&(this._$Ej.set(t,a??e??this[t]),!0!==r||void 0!==a)||(this._$AL.has(t)||(this.hasUpdated||s||(e=void 0),this._$AL.set(t,e)),!0===i&&this._$Em!==t&&(this._$Eq??=new Set).add(t))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(t){Promise.reject(t)}const t=this.scheduleUpdate();return null!=t&&await t,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(const[t,e]of this._$Ep)this[t]=e;this._$Ep=void 0}const t=this.constructor.elementProperties;if(t.size>0)for(const[e,s]of t){const{wrapped:t}=s,i=this[e];!0!==t||this._$AL.has(e)||void 0===i||this.C(e,void 0,s,i)}}let t=!1;const e=this._$AL;try{t=this.shouldUpdate(e),t?(this.willUpdate(e),this._$EO?.forEach(t=>t.hostUpdate?.()),this.update(e)):this._$EM()}catch(e){throw t=!1,this._$EM(),e}t&&this._$AE(e)}willUpdate(t){}_$AE(t){this._$EO?.forEach(t=>t.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(t)),this.updated(t)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(t){return!0}update(t){this._$Eq&&=this._$Eq.forEach(t=>this._$ET(t,this[t])),this._$EM()}updated(t){}firstUpdated(t){}};x.elementStyles=[],x.shadowRootOptions={mode:"open"},x[f("elementProperties")]=new Map,x[f("finalized")]=new Map,m?.({ReactiveElement:x}),(h.reactiveElementVersions??=[]).push("2.1.2");const $=globalThis,w=t=>t,k=$.trustedTypes,S=k?k.createPolicy("lit-html",{createHTML:t=>t}):void 0,C="$lit$",z=`lit$${Math.random().toFixed(9).slice(2)}$`,M="?"+z,D=`<${M}>`,E=document,N=()=>E.createComment(""),F=t=>null===t||"object"!=typeof t&&"function"!=typeof t,A=Array.isArray,T="[ \t\n\f\r]",I=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,R=/-->/g,B=/>/g,O=RegExp(`>|${T}(?:([^\\s"'>=/]+)(${T}*=${T}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`,"g"),L=/'/g,P=/"/g,U=/^(?:script|style|textarea|title)$/i,W=t=>(e,...s)=>({_$litType$:t,strings:e,values:s}),H=W(1),j=W(2),G=Symbol.for("lit-noChange"),K=Symbol.for("lit-nothing"),q=new WeakMap,V=E.createTreeWalker(E,129);function Y(t,e){if(!A(t)||!t.hasOwnProperty("raw"))throw Error("invalid template strings array");return void 0!==S?S.createHTML(e):e}const Z=(t,e)=>{const s=t.length-1,i=[];let r,a=2===e?"<svg>":3===e?"<math>":"",n=I;for(let e=0;e<s;e++){const s=t[e];let o,l,c=-1,d=0;for(;d<s.length&&(n.lastIndex=d,l=n.exec(s),null!==l);)d=n.lastIndex,n===I?"!--"===l[1]?n=R:void 0!==l[1]?n=B:void 0!==l[2]?(U.test(l[2])&&(r=RegExp("</"+l[2],"g")),n=O):void 0!==l[3]&&(n=O):n===O?">"===l[0]?(n=r??I,c=-1):void 0===l[1]?c=-2:(c=n.lastIndex-l[2].length,o=l[1],n=void 0===l[3]?O:'"'===l[3]?P:L):n===P||n===L?n=O:n===R||n===B?n=I:(n=O,r=void 0);const p=n===O&&t[e+1].startsWith("/>")?" ":"";a+=n===I?s+D:c>=0?(i.push(o),s.slice(0,c)+C+s.slice(c)+z+p):s+z+(-2===c?e:p)}return[Y(t,a+(t[s]||"<?>")+(2===e?"</svg>":3===e?"</math>":"")),i]};class X{constructor({strings:t,_$litType$:e},s){let i;this.parts=[];let r=0,a=0;const n=t.length-1,o=this.parts,[l,c]=Z(t,e);if(this.el=X.createElement(l,s),V.currentNode=this.el.content,2===e||3===e){const t=this.el.content.firstChild;t.replaceWith(...t.childNodes)}for(;null!==(i=V.nextNode())&&o.length<n;){if(1===i.nodeType){if(i.hasAttributes())for(const t of i.getAttributeNames())if(t.endsWith(C)){const e=c[a++],s=i.getAttribute(t).split(z),n=/([.?@])?(.*)/.exec(e);o.push({type:1,index:r,name:n[2],strings:s,ctor:"."===n[1]?st:"?"===n[1]?it:"@"===n[1]?rt:et}),i.removeAttribute(t)}else t.startsWith(z)&&(o.push({type:6,index:r}),i.removeAttribute(t));if(U.test(i.tagName)){const t=i.textContent.split(z),e=t.length-1;if(e>0){i.textContent=k?k.emptyScript:"";for(let s=0;s<e;s++)i.append(t[s],N()),V.nextNode(),o.push({type:2,index:++r});i.append(t[e],N())}}}else if(8===i.nodeType)if(i.data===M)o.push({type:2,index:r});else{let t=-1;for(;-1!==(t=i.data.indexOf(z,t+1));)o.push({type:7,index:r}),t+=z.length-1}r++}}static createElement(t,e){const s=E.createElement("template");return s.innerHTML=t,s}}function J(t,e,s=t,i){if(e===G)return e;let r=void 0!==i?s._$Co?.[i]:s._$Cl;const a=F(e)?void 0:e._$litDirective$;return r?.constructor!==a&&(r?._$AO?.(!1),void 0===a?r=void 0:(r=new a(t),r._$AT(t,s,i)),void 0!==i?(s._$Co??=[])[i]=r:s._$Cl=r),void 0!==r&&(e=J(t,r._$AS(t,e.values),r,i)),e}class Q{constructor(t,e){this._$AV=[],this._$AN=void 0,this._$AD=t,this._$AM=e}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(t){const{el:{content:e},parts:s}=this._$AD,i=(t?.creationScope??E).importNode(e,!0);V.currentNode=i;let r=V.nextNode(),a=0,n=0,o=s[0];for(;void 0!==o;){if(a===o.index){let e;2===o.type?e=new tt(r,r.nextSibling,this,t):1===o.type?e=new o.ctor(r,o.name,o.strings,this,t):6===o.type&&(e=new at(r,this,t)),this._$AV.push(e),o=s[++n]}a!==o?.index&&(r=V.nextNode(),a++)}return V.currentNode=E,i}p(t){let e=0;for(const s of this._$AV)void 0!==s&&(void 0!==s.strings?(s._$AI(t,s,e),e+=s.strings.length-2):s._$AI(t[e])),e++}}class tt{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(t,e,s,i){this.type=2,this._$AH=K,this._$AN=void 0,this._$AA=t,this._$AB=e,this._$AM=s,this.options=i,this._$Cv=i?.isConnected??!0}get parentNode(){let t=this._$AA.parentNode;const e=this._$AM;return void 0!==e&&11===t?.nodeType&&(t=e.parentNode),t}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(t,e=this){t=J(this,t,e),F(t)?t===K||null==t||""===t?(this._$AH!==K&&this._$AR(),this._$AH=K):t!==this._$AH&&t!==G&&this._(t):void 0!==t._$litType$?this.$(t):void 0!==t.nodeType?this.T(t):(t=>A(t)||"function"==typeof t?.[Symbol.iterator])(t)?this.k(t):this._(t)}O(t){return this._$AA.parentNode.insertBefore(t,this._$AB)}T(t){this._$AH!==t&&(this._$AR(),this._$AH=this.O(t))}_(t){this._$AH!==K&&F(this._$AH)?this._$AA.nextSibling.data=t:this.T(E.createTextNode(t)),this._$AH=t}$(t){const{values:e,_$litType$:s}=t,i="number"==typeof s?this._$AC(t):(void 0===s.el&&(s.el=X.createElement(Y(s.h,s.h[0]),this.options)),s);if(this._$AH?._$AD===i)this._$AH.p(e);else{const t=new Q(i,this),s=t.u(this.options);t.p(e),this.T(s),this._$AH=t}}_$AC(t){let e=q.get(t.strings);return void 0===e&&q.set(t.strings,e=new X(t)),e}k(t){A(this._$AH)||(this._$AH=[],this._$AR());const e=this._$AH;let s,i=0;for(const r of t)i===e.length?e.push(s=new tt(this.O(N()),this.O(N()),this,this.options)):s=e[i],s._$AI(r),i++;i<e.length&&(this._$AR(s&&s._$AB.nextSibling,i),e.length=i)}_$AR(t=this._$AA.nextSibling,e){for(this._$AP?.(!1,!0,e);t!==this._$AB;){const e=w(t).nextSibling;w(t).remove(),t=e}}setConnected(t){void 0===this._$AM&&(this._$Cv=t,this._$AP?.(t))}}class et{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(t,e,s,i,r){this.type=1,this._$AH=K,this._$AN=void 0,this.element=t,this.name=e,this._$AM=i,this.options=r,s.length>2||""!==s[0]||""!==s[1]?(this._$AH=Array(s.length-1).fill(new String),this.strings=s):this._$AH=K}_$AI(t,e=this,s,i){const r=this.strings;let a=!1;if(void 0===r)t=J(this,t,e,0),a=!F(t)||t!==this._$AH&&t!==G,a&&(this._$AH=t);else{const i=t;let n,o;for(t=r[0],n=0;n<r.length-1;n++)o=J(this,i[s+n],e,n),o===G&&(o=this._$AH[n]),a||=!F(o)||o!==this._$AH[n],o===K?t=K:t!==K&&(t+=(o??"")+r[n+1]),this._$AH[n]=o}a&&!i&&this.j(t)}j(t){t===K?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,t??"")}}class st extends et{constructor(){super(...arguments),this.type=3}j(t){this.element[this.name]=t===K?void 0:t}}let it=class extends et{constructor(){super(...arguments),this.type=4}j(t){this.element.toggleAttribute(this.name,!!t&&t!==K)}};class rt extends et{constructor(t,e,s,i,r){super(t,e,s,i,r),this.type=5}_$AI(t,e=this){if((t=J(this,t,e,0)??K)===G)return;const s=this._$AH,i=t===K&&s!==K||t.capture!==s.capture||t.once!==s.once||t.passive!==s.passive,r=t!==K&&(s===K||i);i&&this.element.removeEventListener(this.name,this,s),r&&this.element.addEventListener(this.name,this,t),this._$AH=t}handleEvent(t){"function"==typeof this._$AH?this._$AH.call(this.options?.host??this.element,t):this._$AH.handleEvent(t)}}class at{constructor(t,e,s){this.element=t,this.type=6,this._$AN=void 0,this._$AM=e,this.options=s}get _$AU(){return this._$AM._$AU}_$AI(t){J(this,t)}}const nt={I:tt},ot=$.litHtmlPolyfillSupport;ot?.(X,tt),($.litHtmlVersions??=[]).push("3.3.3");const lt=globalThis;let ct=class extends x{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){const t=super.createRenderRoot();return this.renderOptions.renderBefore??=t.firstChild,t}update(t){const e=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(t),this._$Do=((t,e,s)=>{const i=s?.renderBefore??e;let r=i._$litPart$;if(void 0===r){const t=s?.renderBefore??null;i._$litPart$=r=new tt(e.insertBefore(N(),t),t,void 0,s??{})}return r._$AI(t),r})(e,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return G}};ct._$litElement$=!0,ct.finalized=!0,lt.litElementHydrateSupport?.({LitElement:ct});const dt=lt.litElementPolyfillSupport;dt?.({LitElement:ct}),(lt.litElementVersions??=[]).push("4.2.2");const pt={solar:"#ff9800",gridImport:"#488fc2",gridExport:"#8353d1",batteryOut:"#4db6ac",battery:"#4db6ac",home:"#5BC8D8",ev:"#8DC892",inverter:"#96CAEE"},_t=["#FF8A65","#AED581","#CE93D8","#64B5F6","#ff9800","#96CAEE"],ht="#86A9B4";function ut(t){if(null==t||isNaN(t))return"— W";return Math.abs(t)>=1e3?`${(t/1e3).toFixed(1)} kW`:`${Math.round(t)} W`}function gt(t,e){if(!t)return"—";try{return new Date(t).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit",timeZone:e||void 0})}catch(t){return"—"}}function mt(t){const e=Math.abs(t);if(e<=0)return 4;const s=4-.9*Math.log10(Math.max(e,1));return Math.max(.5,Math.min(4,s))}function ft(t){if(!t)return"EUR";const e=t.states?.["sensor.sem_daily_costs"];return e?.attributes?.unit_of_measurement?e.attributes.unit_of_measurement:t.config?.currency||"EUR"}function yt(t){const e=t||document.documentElement,s=getComputedStyle(e),i=(t,e)=>s.getPropertyValue(t).trim()||e,r=i("--primary-text-color","#e0e0e0"),a=i("--secondary-text-color","#888888"),n=i("--card-background-color","rgba(30,35,45,0.5)"),o=i("--divider-color","rgba(255,255,255,0.12)"),l=i("--secondary-background-color","rgba(255,255,255,0.06)"),c=i("--ha-card-box-shadow","0 2px 8px rgba(0,0,0,0.15)"),d=i("--primary-color","#42a5f5"),p=(()=>{const t=i("--primary-background-color","#111"),e=t.match(/\d+/g);if(e&&e.length>=3){return(.299*+e[0]+.587*+e[1]+.114*+e[2])/255<.5}return!(t.startsWith("#f")||t.startsWith("#e")||t.startsWith("#d")||t.startsWith("#c")||t.startsWith("rgb(2"))})();return{text:r,textSec:a,cardBg:n,divider:o,bgSec:l,shadow:c,accent:d,isDark:p,textTertiary:p?"rgba(255,255,255,0.45)":"rgba(0,0,0,0.50)",textDisabled:p?"rgba(255,255,255,0.26)":"rgba(0,0,0,0.30)",surface:p?"rgba(255,255,255,0.06)":"rgba(0,0,0,0.03)",surfaceHover:p?"rgba(255,255,255,0.10)":"rgba(0,0,0,0.06)",surfaceBorder:p?"rgba(255,255,255,0.12)":"rgba(0,0,0,0.08)",dotColor:p?"rgba(128,128,128,0.05)":"rgba(128,128,128,0.06)",glowAlpha:p?.05:.03,tooltipBg:p?"rgba(20,20,30,0.95)":"rgba(255,255,255,0.95)",tooltipText:p?"#e0e0e0":"#333333",tooltipBorder:p?"rgba(255,255,255,0.15)":"rgba(0,0,0,0.12)"}}function vt(t,e,s){return`radial-gradient(ellipse 70% 60% at 50% 25%, ${e}${Math.round(.06*255).toString(16).padStart(2,"0")} 0%, transparent 100%),\n            radial-gradient(circle at 2px 2px, ${t.dotColor} 0.7px, transparent 0.7px)`}function bt(t,e){if(!t?.states)return"";const s=e||"sensor.sem_";return["pv1","pv2","pv3","pv4"].map(e=>t.states[`${s}pv_string_${e}_power`]?.state??"").join("|")}function xt(t,e){if(!t||!t.states)return[];const s=e||"sensor.sem_",i=[];for(const e of["pv1","pv2","pv3","pv4"]){const r=`${s}pv_string_${e}_power`,a=t.states[r];if(!a||!0===a.attributes?.restored)continue;const n=parseFloat(a.state),o=`${s}pv_string_${e}_daily_energy`,l=t.states[o],c=l?parseFloat(l.state):NaN;i.push({slot:e,watts:isNaN(n)?null:n,entityId:r,energyKwh:isNaN(c)?null:c,energyEntityId:l?o:null,name:a.attributes?.string_name||l?.attributes?.string_name||"PV"+e.replace(/^pv/,"")})}return i.length>=2?i:[]}function $t(t){return null==t||isNaN(t)?"— kW":`${(Math.abs(t)/1e3).toFixed(2)} kW`}const wt="\n    .pv-strings-row {\n        display: flex;\n        flex-wrap: wrap;\n        gap: 6px;\n        padding: 6px 12px;\n        font-family: 'Segoe UI','Roboto',sans-serif;\n        font-size: 12px;\n    }\n    .pv-chip {\n        display: inline-flex;\n        align-items: baseline;\n        gap: 4px;\n        padding: 2px 8px;\n        background: rgba(255, 152, 0, 0.10);\n        border: 1px solid rgba(255, 152, 0, 0.25);\n        border-radius: 999px;\n        color: var(--secondary-text-color, #aaa);\n        cursor: pointer;\n        transition: background 120ms ease;\n    }\n    .pv-chip:hover { background: rgba(255, 152, 0, 0.18); }\n    .pv-chip-label {\n        font-size: 11px;\n        letter-spacing: 0.5px;\n        text-transform: uppercase;\n        opacity: 0.7;\n    }\n    .pv-chip-value {\n        color: var(--sem-solar, #ff9800);\n        font-weight: 600;\n        font-variant-numeric: tabular-nums;\n    }\n";function kt(t,e,s){customElements.get(t)||(customElements.define(t,e),s&&(window.customCards=window.customCards||[],window.customCards.push(s)))}const St={normal:"normal",negated:"sign_negated",learning:"learning"},Ct={tibber:"Tibber",amber:"Amber",octopus:"Octopus Energy",nordpool:"Nord Pool",nordpool_official:"Nord Pool",awattar:"aWATTar",entsoe:"ENTSO-e"},zt={diag_grid_mode:{combined:"grid_combined",split:"grid_split","split-declared":"grid_split","split-declared-unverified":"grid_split_unverified","split-lowconf":"grid_split_unverified",manual:"grid_manual"},diag_grid_sign:St,diag_battery_sign:St,heat_pump_mode:{blocked:"blocked",normal:"normal",boost:"boost",force_on:"force_on"},diag_charger_control:{number:"charger_control_number",service:"charger_control_service",none:""},tariff_provider:{custom:"custom",static:"tariff_static",calendar:"tariff_calendar",unknown:"unknown"},load_management_status:{normal:"normal",warning:"warning",shedding:"shedding",emergency:"emergency",disabled:"disabled",error:"error",idle:"idle"}},Mt=new Set(["diag_battery_sign"]);function Dt(t,e,s){if(Object.prototype.hasOwnProperty.call(t,e)){const i=t[e];return i?s(i):""}return null}function Et(t,e,s){const i=String(e??"").trim();if(!i)return"";const r=zt[t];if(!r)return i;if(Mt.has(t))return i.replace(/[a-z_]+/g,t=>{const e=Dt(r,t,s);return null===e?t:e});const a=Dt(r,i.toLowerCase(),s);if(null!==a)return a;if("tariff_provider"===t){const t=Ct[i.toLowerCase()];if(t)return t}return i}const Nt="—";function Ft(t){if(!t)return!0;const e=t.state;return null==e||("unavailable"===e||"unknown"===e||""===e||Number.isNaN(parseFloat(e)))}function At(t){if(Ft(t))return null;const e=parseFloat(t.state);return Number.isFinite(e)?e:null}function Tt(t,e=0){return null!=t&&Number.isFinite(t)?t.toFixed(e):Nt}function It(t,e=!1){return e||null==t||Number.isNaN(t)?{label:Nt,fraction:0,known:!1}:{label:`${t.toFixed(0)}%`,fraction:Math.max(0,Math.min(1,t/100)),known:!0}}function Rt(t,e){let s=!1;for(const i of e||[]){const e=i?t?.[i]:void 0;if(e&&(s=!0,"unavailable"!==e.state&&"unknown"!==e.state))return!1}return s}function Bt(t,e){let s=0;for(const i of e||[])if(i&&(s++,null!=At(t?.[i])))return!1;return s>0}const Ot=a`
    ha-card {
        background-color: var(--card-background-color);
        color: var(--primary-text-color);
        border: 1px solid var(--divider-color);
        border-radius: 16px;
        box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0, 0, 0, 0.08));
        max-width: 900px;
        font-family: 'Segoe UI', 'Roboto', sans-serif;
        transition: box-shadow 0.3s cubic-bezier(0.4, 0, 0.2, 1),
                    border-color 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        --chip-background: var(--secondary-background-color);
        --primary-font-family: 'Segoe UI', 'Roboto', sans-serif;
    }
    ha-card:hover {
        box-shadow: var(--ha-card-box-shadow, 0 4px 16px rgba(0, 0, 0, 0.12));
    }
`;class Lt extends ct{constructor(){super(),this._hass=null,this._config=null,this._lang=null,this._localizeReady=!1,this._prevVals={},this._frozenEntities={},this._holdTimers={},this._holdIntervals={},this._cachedTheme=null,this._updateTimer=null}set hass(t){this._hass,this._hass=t;const e=t?.language,s="function"==typeof semLocalize;let i=!1;if((e!==this._lang||s&&!this._localizeReady)&&(this._lang=e,this._localizeReady=s,i=!0),this._isFrozen()&&!i)return;const r=this.constructor.watchedEntities||[];if(!i&&Rt(t.states,r))return;let a=!1;for(const e of r)if(this._prevVals[e]!==this._watchedValue(t,e)){a=!0;break}if(a||i){for(const e of r)this._prevVals[e]=this._watchedValue(t,e);this._scheduleUpdate()}}_watchedValue(t,e){const s=t.states[e],i=this.constructor.watchedAttributes?.[e];return i?JSON.stringify([s?.state??null,...i.map(t=>s?.attributes?.[t]??null)]):s?.state}get hass(){return this._hass}_fireMoreInfo(t){t&&this.dispatchEvent(new CustomEvent("hass-more-info",{detail:{entityId:t},bubbles:!0,composed:!0}))}_scheduleUpdate(){this._updateTimer||(this._updateTimer=setTimeout(()=>{this._updateTimer=null,this.requestUpdate()},16))}_theme(){const t=getComputedStyle(document.documentElement).getPropertyValue("--primary-background-color").trim();return this._cachedTheme&&this._cachedThemeKey===t||(this._cachedThemeKey=t,this._cachedTheme=yt()),this._cachedTheme}_t(t){return t?"function"==typeof semLocalize?semLocalize(t,this._hass?.language):t:""}_valLabel(t){const e=this._hass?.states?.[`${this._prefix||"sensor.sem_"}${t}`];return Et(t,e&&"unavailable"!==e.state&&"unknown"!==e.state?e.state:"",t=>this._t(t))}_forecastProviderLabel(t){if(!t)return"";return{solcast:"Solcast",forecast_solar:"Forecast.Solar",open_meteo:"Open-Meteo",helios:"Helios",custom:this._t("custom")||"Custom"}[t]||t}_state(t,e=null){const s=this._frozenEntities[t];return s?s.value:At(this._hass?.states[t])??e}_stateStr(t){const e=this._frozenEntities[t];if(e)return String(e.value);const s=this._hass?.states[t];return s&&"unavailable"!==s.state&&"unknown"!==s.state?s.state:""}_unitOf(t){const e=this._hass?.states[t];return e&&e.attributes&&e.attributes.unit_of_measurement||""}_kgUnit(t){return this._unitOf(`${this._prefix}${t}`)||"kg"}_pcEntity(t,e,s){const i=this._hass?.states||{},r=new RegExp(`^${t}\\.sem_charger_.+_${e}$`);let a=Object.keys(i).filter(t=>r.test(t));return"night_charging"===e&&(a=a.filter(t=>!t.endsWith("_smart_night_charging"))),a.sort(),a.length?a[0]:s}_stateAttrs(t){return this._hass?.states[t]?.attributes||{}}_freezeEntity(t,e){const s=this._frozenEntities[t];s?.timer&&clearTimeout(s.timer),this._frozenEntities[t]={value:e,timer:setTimeout(()=>{delete this._frozenEntities[t],this.requestUpdate()},1500)}}_isFrozen(){return Object.keys(this._frozenEntities).length>0}async _callService(t,e,s){if(this._hass)try{await this._hass.callService(t,e,s)}catch(t){console.error(`[SEM ${this.tagName}]`,t)}}_setNumber(t,e){const s=this._hass?.states[t];if(!s)return;const i=parseFloat(s.attributes.min)||0,r=parseFloat(s.attributes.max)||100,a=Math.max(i,Math.min(r,e));this._freezeEntity(t,a),this.requestUpdate(),this._callService("number","set_value",{entity_id:t,value:a})}_stepNumber(t,e){const s=this._hass?.states[t];if(!s)return;const i=this._frozenEntities[t],r=i?i.value:parseFloat(s.state)||0,a=parseFloat(s.attributes.step)||1;this._setNumber(t,r+e*a)}_toggleSwitch(t){const e=this._hass?.states[t];if(!e)return;const s="on"===e.state?"off":"on";this._freezeEntity(t,s),this.requestUpdate();const i="on"===e.state?"turn_off":"turn_on";this._callService("switch",i,{entity_id:t})}_selectOption(t,e){this._freezeEntity(t,e),this.requestUpdate(),this._callService("select","select_option",{entity_id:t,option:e})}_pressButton(t){this._callService("button","press",{entity_id:t})}_startHold(t,e){this._stopHold(t),this._holdTimers[t]=setTimeout(()=>{this._holdIntervals[t]=setInterval(()=>{this._stepNumber(t,e)},150)},400)}_stopHold(t){clearTimeout(this._holdTimers[t]),clearInterval(this._holdIntervals[t]),delete this._holdTimers[t],delete this._holdIntervals[t]}updated(){if(window._semDebug){this.style.outline="2px solid red",this.style.outlineOffset="-2px",clearTimeout(this._debugFlashTimer),this._debugFlashTimer=setTimeout(()=>{this.style.outline="",this.style.outlineOffset=""},200);const t=this.tagName.toLowerCase();window._semRenderLog||(window._semRenderLog={}),window._semRenderLog[t]=(window._semRenderLog[t]||0)+1}}connectedCallback(){super.connectedCallback(),window._semDebug&&console.log(`[SEM DEBUG] ${this.tagName} connectedCallback`),this.hasUpdated&&this.requestUpdate(),this._localizeReady||"function"==typeof semLocalize?"function"==typeof semLocalize&&(this._localizeReady=!0):(this._onLocalizeReady=()=>{document.removeEventListener("sem-localize-ready",this._onLocalizeReady),this._onLocalizeReady=null,this._localizeReady=!0,this._hass&&this.requestUpdate()},document.addEventListener("sem-localize-ready",this._onLocalizeReady))}disconnectedCallback(){super.disconnectedCallback(),window._semDebug&&console.log(`[SEM DEBUG] ${this.tagName} disconnectedCallback !!!`),this._onLocalizeReady&&(document.removeEventListener("sem-localize-ready",this._onLocalizeReady),this._onLocalizeReady=null),this._updateTimer&&(clearTimeout(this._updateTimer),this._updateTimer=null);for(const t of Object.keys(this._holdTimers))this._stopHold(t);for(const t of Object.keys(this._frozenEntities))clearTimeout(this._frozenEntities[t]?.timer);this._frozenEntities={}}setConfig(t){this._config=t}getCardSize(){return 4}static getStubConfig(){return{}}}kt("sem-title-card",class extends Lt{static get watchedEntities(){return[]}constructor(){super(),this._renderedSubtitle=null,this._templateUnsub=null,this._templateSubbed=!1,this._templateGen=0}setConfig(t){super.setConfig(t),this._unsubTemplate(),this._renderedSubtitle=null}_hasJinja(t){return t&&(t.includes("{%")||t.includes("{{"))}set hass(t){this._hass,this._hass=t;const e=t?.language,s="function"==typeof semLocalize;(e!==this._lang||s&&!this._localizeReady)&&(this._lang=e,this._localizeReady=s,this.requestUpdate()),this.isConnected&&this._hasJinja(this._config?.subtitle)&&!this._templateSubbed&&this._subscribeTemplate()}_subscribeTemplate(){if(!this._hass?.connection||this._templateSubbed)return;this._templateSubbed=!0;const t=this._templateGen,e=this._config.subtitle;this._hass.connection.subscribeMessage(e=>{if(t!==this._templateGen)return;const s=e.result;s!==this._renderedSubtitle&&(this._renderedSubtitle=s,this.requestUpdate())},{type:"render_template",template:e,variables:{}}).then(e=>{t===this._templateGen?this._templateUnsub=e:e()}).catch(()=>{t===this._templateGen&&(this._renderedSubtitle=this._config.subtitle,this.requestUpdate())})}_unsubTemplate(){this._templateGen++,this._templateSubbed=!1,this._templateUnsub&&(this._templateUnsub(),this._templateUnsub=null)}connectedCallback(){super.connectedCallback(),this._hass&&this._hasJinja(this._config?.subtitle)&&this._subscribeTemplate()}disconnectedCallback(){super.disconnectedCallback(),this._unsubTemplate()}render(){if(!this._config)return K;const t=this._t(this._config.title_key||this._config.title||"");let e="";e=this._hasJinja(this._config.subtitle)?this._renderedSubtitle||"":this._t(this._config.subtitle||"");const s=this._theme();return H`
            <style>
                :host { display: block; }
                .sem-title-wrap {
                    padding: 8px 0 0 0;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                }
                .title {
                    font-size: 16px;
                    font-weight: 600;
                    letter-spacing: 0.5px;
                    color: ${s.text};
                    line-height: 1.3;
                    padding: 0 16px;
                }
                .subtitle {
                    font-size: 12px;
                    color: ${s.textSec};
                    margin-top: 2px;
                    line-height: 1.4;
                    padding: 0 16px;
                }
                .divider {
                    height: 1px;
                    margin: 4px 16px 0;
                    background: linear-gradient(90deg, rgba(150,202,238,0.25) 0%, transparent 70%);
                }
            </style>
            <div class="sem-title-wrap">
                <div class="title">${t}</div>
                ${e?H`<div class="subtitle">${e}</div>`:K}
                <div class="divider"></div>
            </div>
        `}getCardSize(){return 1}static getStubConfig(){return{title:"Section Title"}}},{type:"sem-title-card",name:"SEM Title Card",description:"Runtime-translated section header for SEM dashboard",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-title-card"});class Pt extends Lt{static properties={...Lt.properties,_available:{state:!0}};setConfig(t){if(!t?.requires||!t?.card)throw new Error('sem-require: "requires" and "card" are mandatory');this._config=t,this._available=!!customElements.get(t.requires),this._inner=null,this._available||customElements.whenDefined(t.requires).then(()=>{this._available=!0,this._inner=null,this.requestUpdate()})}set hass(t){this._hass=t,this._inner&&(this._inner.hass=t),this.requestUpdate()}async _buildInner(){if(this._inner||!this._available)return;const t=await window.loadCardHelpers();this._inner=t.createCardElement(this._config.card),this._hass&&(this._inner.hass=this._hass),this.requestUpdate()}render(){if(!this._config)return K;if(this._available)return this._inner?H`${this._inner}`:(this._buildInner(),K);const t=this._config.name||this._config.requires;return H`
            <ha-card>
                <div class="notice">
                    <ha-icon icon="mdi:puzzle-outline"></ha-icon>
                    <div class="text">
                        <div class="title">${this._t("require_missing_title").replace("{name}",t)}</div>
                        <div class="body">${this._t("require_missing_body").replace("{name}",t)}</div>
                    </div>
                </div>
            </ha-card>
        `}static styles=a`
        .notice {
            display: flex; gap: 14px; align-items: center;
            padding: 16px;
        }
        .notice ha-icon { --mdc-icon-size: 30px; color: var(--warning-color, #ffa726); }
        .title { font-weight: 600; margin-bottom: 4px; }
        .body { font-size: 13px; opacity: 0.85; line-height: 1.4; }
    `;getCardSize(){return this._inner?.getCardSize?.()||3}}kt("sem-require",Pt,{type:"sem-require",name:"SEM Require Wrapper",description:"Renders a card only when its HACS dependency is installed; otherwise a friendly install notice",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-require",preview:!1});function Ut(t){return`${String(t.getHours()).padStart(2,"0")}:${String(t.getMinutes()).padStart(2,"0")}`}function Wt({targetKw:t,usedKwh:e,allowedW:s,now:i=new Date}){const r=function(t){const e=Number(t);return!Number.isFinite(e)||e<=0?null:.25*e}(t);if(null===r)return null;const a=null==e?NaN:Number(e);if(!Number.isFinite(a))return null;const{start:n,end:o}=function(t=new Date){const e=new Date(t);e.setMinutes(15*Math.floor(e.getMinutes()/15),0,0);const s=new Date(e.getTime()+9e5);return{start:e,end:s,elapsedS:Math.max(0,(t-e)/1e3)}}(i),l=null==s?NaN:Number(s);return{label:`${Ut(n)}–${Ut(o)}`,usedKwh:a,budgetKwh:r,fraction:Math.max(0,Math.min(1,a/r)),overBudget:a>=r,allowedKw:Number.isFinite(l)?l/1e3:null}}function Ht(t){return!!t?.attributes?.peak_limit_unlimited}function jt(t,e){if(Ht(t))return e;const s=parseFloat(t?.state);return Number.isFinite(s)?`${s.toFixed(1)} kW`:"—"}const Gt=(t,e)=>"function"==typeof semLocalize?semLocalize(t,e?.language):t,Kt=(t,e)=>null==t?Nt:e(t),qt=t=>t.toFixed(0)+"%",Vt=t=>t.toFixed(1)+" kWh",Yt={home:{titleKey:"home",subtitleKey:"home_sub",color:"#5BC8D8",icon:()=>j`
            <path d="M-20,2 L0,-16 L20,2" stroke-width="2"/>
            <rect x="-15" y="2" width="30" height="22" rx="2" stroke-width="2"/>
            <rect x="-5" y="12" width="10" height="12" stroke-width="1.5"/>`},energy:{titleKey:"energy",subtitleKey:"energy_sub",color:"#ff9800",icon:()=>j`
            <path d="M-4,-18 L-10,2 L-2,2 L-6,18 L12,-4 L2,-4 L8,-18 Z" stroke-width="2"/>`},battery:{titleKey:"battery",subtitleKey:"battery_sub",color:"#4db6ac",icon:()=>j`
            <rect x="-10" y="-16" width="20" height="32" rx="4" stroke-width="2"/>
            <rect x="-4" y="-20" width="8" height="5" rx="2" fill="currentColor" opacity="0.4" stroke="none"/>
            <line x1="-5" y1="-4" x2="5" y2="-4" stroke-width="1.5" opacity="0.5"/>
            <line x1="-5" y1="4" x2="5" y2="4" stroke-width="1.5" opacity="0.5"/>`},ev:{titleKey:"ev_charging",subtitleKey:"ev_sub",color:"#8DC892",icon:()=>j`
            <rect x="-12" y="-14" width="24" height="24" rx="5" stroke-width="2"/>
            <path d="M-3,-6 L-1,0 L-5,0 L3,8" stroke-width="2" fill="none"/>
            <line x1="0" y1="10" x2="0" y2="16" stroke-width="2"/>
            <circle cx="0" cy="18" r="2" fill="currentColor" opacity="0.4" stroke="none"/>`},control:{titleKey:"control",subtitleKey:"control_sub",color:"#96CAEE",icon:()=>j`
            <line x1="-12" y1="-12" x2="-12" y2="12" stroke-width="2"/>
            <line x1="0" y1="-12" x2="0" y2="12" stroke-width="2"/>
            <line x1="12" y1="-12" x2="12" y2="12" stroke-width="2"/>
            <circle cx="-12" cy="-4" r="4" fill="currentColor" opacity="0.6" stroke="none"/>
            <circle cx="0" cy="4" r="4" fill="currentColor" opacity="0.6" stroke="none"/>
            <circle cx="12" cy="-8" r="4" fill="currentColor" opacity="0.6" stroke="none"/>`},config:{titleKey:"config_tab_title",subtitleKey:"config_tab_subtitle",color:"#8DC892",icon:()=>j`
            <circle cx="0" cy="0" r="6" stroke-width="2"/>
            <g stroke-width="2" stroke-linecap="round">
                <line x1="0" y1="-16" x2="0" y2="-10"/>
                <line x1="0" y1="10" x2="0" y2="16"/>
                <line x1="-16" y1="0" x2="-10" y2="0"/>
                <line x1="10" y1="0" x2="16" y2="0"/>
                <line x1="-11" y1="-11" x2="-7" y2="-7"/>
                <line x1="7" y1="7" x2="11" y2="11"/>
                <line x1="11" y1="-11" x2="7" y2="-7"/>
                <line x1="-7" y1="7" x2="-11" y2="11"/>
            </g>`},costs:{titleKey:"costs",subtitleKey:"costs_sub",color:"#f06292",icon:()=>j`
            <circle cx="0" cy="0" r="16" stroke-width="2"/>
            <text x="0" y="6" text-anchor="middle" font-size="18" font-weight="700"
                  fill="currentColor" opacity="0.7" stroke="none"
                  font-family="'Segoe UI','Roboto',sans-serif">$</text>`},system:{titleKey:"system",subtitleKey:"system_sub",color:"#96CAEE",icon:()=>j`
            <path d="M-16,4 L-8,-8 L0,0 L6,-12 L10,-4 L16,4" stroke-width="2" fill="none"/>
            <line x1="-16" y1="8" x2="16" y2="8" stroke-width="1" opacity="0.3"/>`},simulation:{titleKey:"simulation",subtitleKey:"simulation_sub",color:"#8353d1",icon:()=>j`
            <path d="M-5,-15 L5,-15 M-4,-15 L-4,-4 L-14,13 Q-15,16 -11,16 L11,16 Q15,16 14,13 L4,-4 L4,-15" stroke-width="2"/>
            <line x1="-9" y1="6" x2="9" y2="6" stroke-width="1.5" opacity="0.6"/>`}};kt("sem-tab-header",class extends Lt{static get watchedEntities(){return[]}constructor(){super(),this._tab="home",this._prefix="sensor.sem_",this._responsiveApplied=!1,this._lastStatsKey=""}connectedCallback(){super.connectedCallback(),this._applyResponsiveContainer()}_applyResponsiveContainer(){this._responsiveApplied||requestAnimationFrame(()=>{let t=this;for(;t;){const e=t.getRootNode()?.host;if(!e)break;if("HUI-VERTICAL-STACK-CARD"===e.tagName){const t=e.parentElement;if(t&&"HUI-CARD"===t.tagName)return t.style.maxWidth="900px",t.style.margin="0 auto",t.style.display="block",void(this._responsiveApplied=!0)}t=e}})}setConfig(t){super.setConfig(t),this._tab=t.tab||"home",this._prefix=t.entity_prefix||"sensor.sem_"}set hass(t){this._hass,this._hass=t;const e=t?.language,s="function"==typeof semLocalize;let i=!1;if((e!==this._lang||s&&!this._localizeReady)&&(this._lang=e,this._localizeReady=s,i=!0),this._isFrozen()&&!i)return;const r=this._buildStatsKey(t);(r!==this._lastStatsKey||i)&&(this._lastStatsKey=r,this.requestUpdate()),this._responsiveApplied||this._applyResponsiveContainer()}_buildStatsKey(t){return t?"home"===this._tab?this._heroValues().join("|"):this._getStatValues().join("|"):""}_getState(t){const e=this._hass?.states[`${this._prefix}${t}`];return Ft(e)?null:parseFloat(e.state)}_getStatLabels(){const t=t=>Gt(t,this._hass),e=this._tab;return"energy"===e?[t("solar"),t("home"),t("self_use")]:"battery"===e?[t("soc"),t("power"),t("health")]:"ev"===e?[t("power"),t("today"),t("session")]:"control"===e?[t("peak"),t("devices"),t("active")]:"config"===e?[t("config_stat_chargers"),t("config_stat_heatpump"),t("config_stat_battery")]:"costs"===e?[t("cost"),t("saved"),t("net")]:"system"===e?[t("score"),t("saved"),t("co2")]:"simulation"===e?[t("simulation_days_stored"),t("simulation_selected"),t("simulation_gaps")]:["—","—","—"]}_getStatValues(){const t=this._tab,e=ft(this._hass)||"EUR",s=t=>s=>s.toFixed(t)+" "+e;if("energy"===t)return[Kt(this._getState("daily_solar_energy"),Vt),Kt(this._getState("daily_home_energy"),Vt),Kt(this._getState("self_consumption_rate"),qt)];if("battery"===t)return[It(this._getState("battery_soc")).label,Kt(this._getState("battery_power"),ut),Kt(this._getState("battery_health_score"),qt)];if("ev"===t)return[Kt(this._getState("ev_power"),ut),Kt(this._getState("daily_ev_energy"),Vt),Kt(this._getState("session_energy"),Vt)];if("control"===t)return[jt(this._hass?.states[`${this._prefix}target_peak_limit`],Gt("uncapped",this._hass)),Kt(this._getState("controllable_devices_count"),t=>t.toFixed(0)),Kt(this._getState("surplus_active_devices"),t=>t.toFixed(0))];if("config"===t){const t=t=>Gt(t,this._hass),e=Object.keys(this._hass?.states||{}).filter(t=>t.startsWith("number.sem_charger_")&&/^number\.sem_charger_.+_minimum_current$/.test(t)).length,s=this._hass?.states[this._prefix.replace(/^sensor\./,"binary_sensor.")+"heat_pump_registered"]?.state;return[String(e),"on"===s?t("on"):void 0===s||"off"===s?t("off"):Nt,It(this._getState("battery_soc")).label]}return"costs"===t?[Kt(this._getState("daily_costs"),s(2)),Kt(this._getState("daily_savings"),s(2)),Kt(this._getState("daily_net_cost"),t=>(t<=0?"+":"")+Math.abs(t).toFixed(2)+" "+e)]:"system"===t?[Kt(this._getState("energy_optimization_score"),t=>t.toFixed(0)),Kt(this._getState("lifetime_total_savings"),s(0)),Kt(this._getState("lifetime_co2_avoided"),t=>t.toFixed(0)+" "+this._kgUnit("lifetime_co2_avoided"))]:[Nt,Nt,Nt]}_heroValues(){return[this._getState("daily_solar_energy"),this._getState("solar_power")]}_renderHomeHero(){const[t,e]=this._heroValues();return H`
            <div class="hero">
                <div class="hero-main">
                    <div class="hero-value">${null==t?Nt:H`${t.toFixed(1)}<span class="unit">kWh</span>`}</div>
                    <div class="hero-label">${Gt("todays_solar_production",this._hass)}</div>
                </div>
                ${e>0?H`
                <div class="hero-now">
                    <ha-icon icon="mdi:white-balance-sunny"></ha-icon>
                    <span>${ut(e)}</span>
                </div>`:K}
            </div>`}render(){if(!this._hass||!this._config)return K;const t=Yt[this._tab]||Yt.home,e=this._config.title||Gt(t.titleKey,this._hass),s=this._config.subtitle||Gt(t.subtitleKey,this._hass),i=t.color,r=this._getStatLabels(),a=this._getStatValues(),n=this._theme(),o=n.isDark?i:`color-mix(in srgb, ${i} 65%, black)`,l=n.isDark?`0 0 12px ${i}40`:"none",c=n.isDark?.3:.18;return H`
            <style>
                :host { display: block; }
                .header-wrap {
                    display: flex; align-items: center; gap: 16px;
                    padding: 16px 20px; position: relative; overflow: hidden;
                    background:
                        radial-gradient(ellipse 80% 70% at 20% 50%, ${i}0D 0%, transparent 70%),
                        radial-gradient(circle at 2px 2px, ${n.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                }
                .icon-ring { position: relative; flex-shrink: 0; width: 64px; height: 64px; }
                .icon-ring svg { width: 100%; height: 100%; }
                /* min-width keeps the title readable next to the stats;
                   when there isn't room for both, the stats wrap below
                   instead of crushing the title to zero width. */
                .title-area { flex: 1 1 auto; min-width: 140px; }
                .tab-title {
                    font-size: 20px; font-weight: 700; color: ${o};
                    letter-spacing: 0.5px; text-shadow: ${l};
                    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
                }
                .tab-subtitle {
                    font-size: 12px; color: var(--secondary-text-color, ${n.textSec});
                    margin-top: 2px; font-weight: 500;
                    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
                }
                .stats { display: flex; gap: 16px; flex-shrink: 0; }
                .stat { text-align: center; min-width: 50px; }
                .stat-value {
                    font-size: 15px; font-weight: 700; font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${n.text});
                }
                .stat-label {
                    font-size: 11px; color: var(--secondary-text-color, ${n.textTertiary});
                    font-weight: 500; margin-top: 1px;
                }
                /* Home hero — Today's production merged from the KPI card
                   (maintainer UI review: chips duplicated the KPI below) */
                .hero { display: flex; align-items: center; gap: 14px; flex-shrink: 0; }
                .hero-main { text-align: left; }
                .hero-value {
                    font-size: 26px; font-weight: 700; line-height: 1.05;
                    color: #ff9800; letter-spacing: -0.5px;
                    font-variant-numeric: tabular-nums; white-space: nowrap;
                }
                .hero-value .unit { font-size: 14px; font-weight: 500; opacity: 0.85; margin-left: 3px; }
                .hero-label {
                    font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px;
                    color: var(--secondary-text-color, ${n.textTertiary});
                    margin-top: 2px;
                }
                .hero-now {
                    display: flex; align-items: center; gap: 5px;
                    padding: 5px 10px; border-radius: 999px;
                    background: var(--secondary-background-color, rgba(255,255,255,0.06));
                    font-size: 12px; color: var(--primary-text-color, ${n.text});
                    white-space: nowrap;
                }
                .hero-now ha-icon { color: #ff9800; --mdc-icon-size: 14px; }
                @media (max-width: 500px) {
                    .hero-value { font-size: 21px; }
                }
                @media (max-width: 500px) {
                    .header-wrap { padding: 12px 14px; gap: 8px 12px; flex-wrap: wrap; }
                    .icon-ring { width: 48px; height: 48px; }
                    .tab-title { font-size: 16px; }
                    .stats { gap: 10px; }
                    .stat-value { font-size: 13px; }
                }
            </style>
            <ha-card>
                <div class="header-wrap">
                    <div class="icon-ring">
                        <svg viewBox="-34 -34 68 68" xmlns="http://www.w3.org/2000/svg">
                            <defs>
                                <filter id="glow-${this._tab}" x="-40%" y="-40%" width="180%" height="180%">
                                    <feGaussianBlur stdDeviation="4" result="blur"/>
                                    <feFlood flood-color="${i}" flood-opacity="${c}"/>
                                    <feComposite in2="blur" operator="in"/>
                                    <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
                                </filter>
                            </defs>
                            <circle r="28" fill="none" stroke="${i}" stroke-width="1.2" opacity="0.25">
                                <animate attributeName="r" values="28;31;28" dur="3s" repeatCount="indefinite"/>
                                <animate attributeName="opacity" values="0.25;0.10;0.25" dur="3s" repeatCount="indefinite"/>
                            </circle>
                            <circle r="24" fill="${i}0F" stroke="${i}" stroke-width="1.5" filter="url(#glow-${this._tab})"/>
                            <g stroke="${i}" fill="none" opacity="0.75" stroke-linecap="round" stroke-linejoin="round">
                                ${t.icon()}
                            </g>
                        </svg>
                    </div>
                    <div class="title-area">
                        <div class="tab-title">${e}</div>
                        <div class="tab-subtitle">${s}</div>
                    </div>
                    ${"home"===this._tab?this._renderHomeHero():H`
                    <div class="stats">
                        ${r.map((t,e)=>H`
                            <div class="stat">
                                <div class="stat-value">${a[e]}</div>
                                <div class="stat-label">${t}</div>
                            </div>
                        `)}
                    </div>`}
                </div>
            </ha-card>
        `}getCardSize(){return 1}static getStubConfig(){return{tab:"home"}}},{type:"sem-tab-header",name:"SEM Tab Header",description:"Lumina-styled tab header with glow icon and live stats",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-tab-header"});const Zt={"clear-night":{icon:"🌙",key:"weather_clear"},cloudy:{icon:"☁️",key:"weather_cloudy"},fog:{icon:"🌫️",key:"weather_fog"},hail:{icon:"🧊",key:"weather_hail"},lightning:{icon:"⚡",key:"weather_thunder"},"lightning-rainy":{icon:"⛈️",key:"weather_thunderstorm"},partlycloudy:{icon:"⛅",key:"weather_partly_cloudy"},pouring:{icon:"🌧️",key:"weather_pouring"},rainy:{icon:"🌦️",key:"weather_rain"},snowy:{icon:"❄️",key:"weather_snow"},"snowy-rainy":{icon:"🌨️",key:"weather_sleet"},sunny:{icon:"☀️",key:"weather_sunny"},windy:{icon:"💨",key:"weather_windy"},"windy-variant":{icon:"💨",key:"weather_windy"},exceptional:{icon:"⚠️",key:"weather_exceptional"}};kt("sem-weather-card",class extends Lt{static get styles(){return[Ot]}constructor(){super(),this._clockTime="--:--",this._clockDate="",this._clockInterval=null}static get watchedEntities(){return[]}setConfig(t){if(!t.entity)throw new Error("sem-weather-card requires entity");super.setConfig(t)}set hass(t){this._hass,this._hass=t;const e=t?.language,s="function"==typeof semLocalize;let i=!1;if((e!==this._lang||s&&!this._localizeReady)&&(this._lang=e,this._localizeReady=s,i=!0),this._isFrozen()&&!i)return;const r=this._config?.entity;if(!r)return;const a=t?.states[r],n=(a?.state||"")+JSON.stringify(a?.attributes?.forecast?.[0]||"")+"|"+(e||"");(n!==this._lastWeatherKey||i)&&(this._lastWeatherKey=n,this.requestUpdate())}get hass(){return this._hass}connectedCallback(){super.connectedCallback(),this._updateClock(),this._clockInterval=setInterval(()=>{this._updateClock()},3e4)}disconnectedCallback(){super.disconnectedCallback(),this._clockInterval&&(clearInterval(this._clockInterval),this._clockInterval=null)}_updateClock(){const t=new Date,e=this._hass?.language||navigator.language||"en",s=this._hass?.config?.time_zone||void 0;this._clockTime=t.toLocaleTimeString(e,{hour:"2-digit",minute:"2-digit",timeZone:s}),this._clockDate=t.toLocaleDateString(e,{weekday:"long",day:"numeric",month:"long",year:"numeric",timeZone:s}),this.requestUpdate()}_renderForecastRows(t,e){const s=this._hass?.language||navigator.language||"en",i=this._hass?.config?.time_zone||void 0;return t.slice(0,e).map(t=>{const e=new Date(t.datetime).toLocaleDateString(s,{weekday:"short",timeZone:i}),r=Zt[t.condition]?.icon||"❓",a=null!=t.templow?Math.round(t.templow):"—",n=null!=t.temperature?Math.round(t.temperature):"—",o="number"==typeof n&&"number"==typeof a?n-a:0,l=Math.max(o/30*100,10),c="number"==typeof n&&"number"==typeof a?(a+n)/2:15,d=Math.min(Math.max((c-0)/30,0),1),p=d>.5?`rgba(255,${Math.round(200-100*d)},0,0.6)`:`rgba(${Math.round(100+200*d)},${Math.round(180+40*d)},255,0.5)`;return H`
                <div class="forecast-row">
                    <span class="f-day">${e}</span>
                    <span class="f-icon">${r}</span>
                    <span class="f-low">${a}°</span>
                    <div class="f-bar-wrap">
                        <div class="f-bar" style="width:${l}%;background:${p}"></div>
                    </div>
                    <span class="f-high">${n}°</span>
                </div>
            `})}_findUsableWeatherEntity(){const t=this._hass?.states;if(!t)return null;const e=Object.keys(t).filter(e=>{if(!e.startsWith("weather."))return!1;const s=t[e];return s&&"unavailable"!==s.state&&"unknown"!==s.state&&s.attributes&&null!=s.attributes.temperature});return e.filter(t=>!t.startsWith("weather.forecast_"))[0]||e[0]||null}render(){if(!this._config)return K;let t=this._config.entity;const e=this._config.forecast_rows||5;let s=this._hass?.states[t];if(!s||"unavailable"===s.state||null==s.attributes?.temperature){const e=this._findUsableWeatherEntity();e&&(t=e,s=this._hass.states[e])}if(!s)return H`
                <ha-card>
                    <div style="padding:16px;color:#ef5350">Entity ${t} not found</div>
                </ha-card>
            `;const i=this._theme(),r=s.state,a=s.attributes,n=null!=a.temperature?Math.round(a.temperature):"—",o=a.temperature_unit||"°C",l=null!=a.humidity?Math.round(a.humidity):"—",c=null!=a.wind_speed?Math.round(a.wind_speed):"—",d=a.wind_speed_unit||"km/h",p=Zt[r]||{icon:"❓",key:""},_=a.forecast||[];return H`
            <style>
                :host { display: block; }
                .wrap {
                    padding: 24px 20px 16px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 35%, rgba(200,220,240,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${i.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${i.text});
                }
                .clock-section {
                    display: flex;
                    justify-content: space-between;
                    align-items: flex-start;
                    margin-bottom: 20px;
                }
                .clock-left { flex: 1; }
                .time {
                    font-size: 48px;
                    font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    letter-spacing: -1px;
                    line-height: 1;
                    color: var(--primary-text-color, ${i.text});
                    text-shadow: 0 0 20px rgba(200,220,240,0.15);
                }
                .date {
                    font-size: 13px;
                    color: var(--secondary-text-color, ${i.textSec});
                    margin-top: 6px;
                    font-weight: 500;
                }
                .weather-current {
                    text-align: right;
                    flex-shrink: 0;
                }
                .weather-icon {
                    font-size: 40px;
                    line-height: 1;
                    filter: drop-shadow(0 0 8px rgba(200,220,240,0.2));
                }
                .weather-label {
                    font-size: 12px;
                    color: var(--secondary-text-color, ${i.textSec});
                    margin-top: 2px;
                    font-weight: 500;
                }
                .temp {
                    font-size: 28px;
                    font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${i.text});
                    text-shadow: 0 0 12px rgba(200,220,240,0.1);
                }
                .weather-details {
                    display: flex;
                    gap: 16px;
                    margin-bottom: 16px;
                    padding-bottom: 14px;
                    border-bottom: 1px solid var(--divider-color, ${i.surfaceBorder});
                }
                .detail {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    font-size: 12px;
                    color: var(--secondary-text-color, ${i.textSec});
                }
                .detail-icon { font-size: 14px; opacity: 0.7; }
                .forecast-rows {
                    display: flex;
                    flex-direction: column;
                    gap: 6px;
                }
                .forecast-row {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    font-size: 13px;
                    font-variant-numeric: tabular-nums;
                    padding: 4px 0;
                }
                .f-day {
                    width: 32px;
                    color: var(--secondary-text-color, ${i.textSec});
                    font-weight: 500;
                    font-size: 12px;
                }
                .f-icon { font-size: 16px; width: 24px; text-align: center; }
                .f-low {
                    width: 30px;
                    text-align: right;
                    color: #78a8d8;
                    font-weight: 500;
                    font-size: 12px;
                }
                .f-bar-wrap {
                    flex: 1;
                    height: 4px;
                    background: var(--secondary-background-color, ${i.surface});
                    border-radius: 2px;
                    overflow: hidden;
                }
                .f-bar {
                    height: 100%;
                    border-radius: 2px;
                    transition: width 0.5s cubic-bezier(0.4,0,0.2,1);
                }
                .f-high {
                    width: 30px;
                    text-align: right;
                    color: #e0a050;
                    font-weight: 600;
                    font-size: 12px;
                }
            </style>
            <ha-card>
                <div class="wrap">
                    <div class="clock-section">
                        <div class="clock-left">
                            <div class="time">${this._clockTime}</div>
                            <div class="date">${this._clockDate}</div>
                        </div>
                        <div class="weather-current">
                            <div class="weather-icon">${p.icon}</div>
                            <div class="weather-label">${this._t(p.key)}</div>
                            <div class="temp">${n}${o}</div>
                        </div>
                    </div>

                    <div class="weather-details">
                        <div class="detail">
                            <span class="detail-icon">💧</span>
                            <span>${l}%</span>
                        </div>
                        <div class="detail">
                            <span class="detail-icon">💨</span>
                            <span>${c} ${d}</span>
                        </div>
                    </div>

                    <div class="forecast-rows">
                        ${_.length?this._renderForecastRows(_,e):K}
                    </div>
                </div>
            </ha-card>
        `}getCardSize(){return 5}static getStubConfig(){return{entity:"weather.home"}}},{type:"sem-weather-card",name:"SEM Weather",description:"Lumina-styled clock + weather card with forecast",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-weather-card",preview:!1});const Xt=[{key:"today",labelKey:"period_today"},{key:"yesterday",labelKey:"period_yesterday"},{key:"week",labelKey:"period_this_week"},{key:"month",labelKey:"period_this_month"},{key:"year",labelKey:"period_this_year"}];kt("sem-period-selector-card",class extends Lt{static get styles(){return[Ot]}static get watchedEntities(){return[]}constructor(){super(),this._active="week",this._firstRender=!0}setConfig(t){super.setConfig(t),t.default_period&&(this._active=t.default_period)}set hass(t){this._hass,this._hass=t;const e=t?.language,s="function"==typeof semLocalize;(e!==this._lang||s&&!this._localizeReady)&&(this._lang=e,this._localizeReady=s,this.requestUpdate())}get hass(){return this._hass}firstUpdated(){this._dispatchPeriod(this._active)}_getPeriod(t){const e=new Date,s=(t=>new Date(t.getFullYear(),t.getMonth(),t.getDate()))(e);switch(t){case"today":return{start:s,end:e,granularity:"hour"};case"yesterday":{const t=new Date(s);return t.setDate(t.getDate()-1),{start:t,end:s,granularity:"hour"}}case"week":{const t=e.getDay()||7,i=new Date(s);return i.setDate(i.getDate()-(t-1)),{start:i,end:e,granularity:"day"}}case"month":return{start:new Date(e.getFullYear(),e.getMonth(),1),end:e,granularity:"day"};case"year":return{start:new Date(e.getFullYear(),0,1),end:e,granularity:"month"};default:return this._getPeriod("week")}}_dispatchPeriod(t){this._active=t,this.requestUpdate();const e=this._getPeriod(t);document.dispatchEvent(new CustomEvent("sem-period-change",{detail:{...e,key:t}}))}render(){if(!this._config)return K;const t=this._theme();return H`
            <style>
                :host { display: block; }
                .sem-period {
                    display: flex;
                    gap: 8px;
                    padding: 12px 16px;
                    justify-content: center;
                    flex-wrap: wrap;
                    background:
                        radial-gradient(ellipse 80% 60% at 50% 50%, rgba(200,220,240,0.04) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${t.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                }
                .btn {
                    border: 1px solid var(--divider-color, ${t.surfaceBorder});
                    background: var(--secondary-background-color, ${t.surface});
                    color: var(--secondary-text-color, ${t.textSec});
                    padding: 8px 18px;
                    border-radius: 12px;
                    font-size: 13px;
                    font-weight: 500;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    font-variant-numeric: tabular-nums;
                    cursor: pointer;
                    transition: all 0.3s cubic-bezier(0.4,0,0.2,1);
                    backdrop-filter: blur(8px);
                    -webkit-backdrop-filter: blur(8px);
                    user-select: none;
                }
                .btn:hover {
                    background: var(--secondary-background-color, ${t.surfaceHover});
                    color: var(--primary-text-color, ${t.text});
                    border-color: var(--divider-color, ${t.surfaceBorder});
                }
                .btn.active {
                    background: rgba(66,165,245,0.18);
                    border-color: rgba(66,165,245,0.40);
                    color: ${t.accent};
                    box-shadow: 0 0 16px rgba(66,165,245,0.12), 0 0 4px rgba(66,165,245,0.08);
                    font-weight: 600;
                }
            </style>
            <ha-card>
                <div class="sem-period">
                    ${Xt.map(t=>H`
                        <button
                            class="btn ${this._active===t.key?"active":""}"
                            role="button"
                            aria-label=${this._t(t.labelKey)}
                            aria-pressed=${this._active===t.key}
                            @click=${()=>this._dispatchPeriod(t.key)}
                        >${this._t(t.labelKey)}</button>
                    `)}
                </div>
            </ha-card>
        `}getCardSize(){return 1}static getStubConfig(){return{}}},{type:"sem-period-selector-card",name:"SEM Period Selector",description:"Glassmorphism period picker for SEM chart cards",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-period-selector-card",preview:!1});const Jt="sensor.sem_",Qt=["daily_co2_avoided","yearly_co2_avoided","lifetime_co2_avoided","yearly_trees_equivalent","lifetime_trees_equivalent"],te=["solar_used_kwh","co2_kg_per_kwh_today"];function ee(t){return Qt.map(e=>`${t}${e}`)}kt("sem-energy-impact-card",class extends Lt{static get watchedEntities(){return ee(Jt)}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||Jt,this._prefix!==Jt&&(this._prevVals={})}set hass(t){this._hass,this._hass=t;const e=t?.language,s="function"==typeof semLocalize;let i=!1;if((e!==this._lang||s&&!this._localizeReady)&&(this._lang=e,this._localizeReady=s,i=!0),this._isFrozen()&&!i)return;const r=ee(this._prefix||Jt);let a=!1;for(const e of r)if(this._prevVals[e]!==this._readKey(t,e)){a=!0;break}if(a||i){for(const e of r)this._prevVals[e]=this._readKey(t,e);this._scheduleUpdate()}}get hass(){return this._hass}_readKey(t,e){const s=t.states[e];return e!==`${this._prefix||Jt}daily_co2_avoided`?s?.state:JSON.stringify([s?.state??null,...te.map(t=>s?.attributes?.[t]??null)])}_val(t){const e=this._stateObj(t);return Ft(e)?null:parseFloat(e.state)}_stateObj(t){return this._hass?.states[`${this._prefix||Jt}${t}`]}_kgUnit(t){return this._unitOf(`${this._prefix||Jt}${t}`)||"kg"}_treeIcon(t){return t>=50?"mdi:forest":t>=10?"mdi:pine-tree":t>=1?"mdi:tree":"mdi:sprout"}render(){if(!this._config)return K;const t=this._theme(),e=this._val("daily_co2_avoided"),s=null==e?Nt:`${e.toFixed(2)} ${this._kgUnit("daily_co2_avoided")}`,i=function(t){if(Ft(t))return"";const e=t.attributes?.solar_used_kwh,s=t.attributes?.co2_kg_per_kwh_today;return Number.isFinite(e)&&Number.isFinite(s)?`${e.toFixed(1)} kWh × ${Math.round(1e3*s)} g/kWh`:""}(this._stateObj("daily_co2_avoided")),r=this._val("yearly_trees_equivalent"),a=this._val("lifetime_trees_equivalent"),n=this._val("yearly_co2_avoided"),o=this._val("lifetime_co2_avoided"),l=(t,e)=>null==t?Nt:`${t.toFixed(0)} ${this._kgUnit(e)}`,c=null==r?Nt:r>=10?r.toFixed(0):r.toFixed(1),d=this._treeIcon(r??0);return H`
            <style>
                :host { display: block; }

                .wrap {
                    padding: 16px;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 25%, rgba(255,152,0,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${t.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI', 'Roboto', sans-serif;
                    color: var(--primary-text-color, ${t.text});
                }

                .tiles {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 12px;
                }

                .tile {
                    display: flex;
                    align-items: flex-start;
                    gap: 10px;
                    padding: 14px;
                    border-radius: 12px;
                    background: ${t.surface};
                    border: 1px solid ${t.surfaceBorder};
                }

                .tile ha-icon {
                    flex-shrink: 0;
                    margin-top: 2px;
                }

                .tile-content {
                    display: flex;
                    flex-direction: column;
                    gap: 4px;
                    min-width: 0;
                }

                .tile-label {
                    font-size: 12px;
                    font-weight: 500;
                    text-transform: uppercase;
                    letter-spacing: 0.3px;
                    color: var(--secondary-text-color, ${t.textSec});
                }

                .tile-hero {
                    font-size: 22px;
                    font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    line-height: 1.1;
                }

                .tile-detail {
                    font-size: 12px;
                    color: var(--secondary-text-color, ${t.textSec});
                }

                .stats {
                    display: flex;
                    gap: 16px;
                    margin-top: 4px;
                    flex-wrap: wrap;
                }

                .stat {
                    display: flex;
                    flex-direction: column;
                    gap: 1px;
                }

                .stat-val {
                    font-size: 13px;
                    font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }

                .stat-lbl {
                    font-size: 12px;
                    text-transform: uppercase;
                    letter-spacing: 0.3px;
                    color: var(--secondary-text-color, ${t.textSec});
                }

                /* Hidden SVG filter */
                .glow-svg {
                    position: absolute;
                    width: 0;
                    height: 0;
                    overflow: hidden;
                }

                @media (max-width: 480px) {
                    .tiles { grid-template-columns: 1fr; }
                }
            </style>

            <!-- SVG glow filter for leaf/tree icons -->
            <svg class="glow-svg" aria-hidden="true">
                <defs>
                    <filter id="leaf-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="3" result="blur"/>
                        <feFlood flood-color="#8DC892" flood-opacity="0.25" result="color"/>
                        <feComposite in="color" in2="blur" operator="in" result="glow"/>
                        <feMerge>
                            <feMergeNode in="glow"/>
                            <feMergeNode in="SourceGraphic"/>
                        </feMerge>
                    </filter>
                </defs>
            </svg>

            <div class="wrap">
                <div class="tiles">

                    <!-- Left tile: Carbon Avoided Today -->
                    <div class="tile">
                        <ha-icon
                            icon="mdi:leaf"
                            style="--mdc-icon-size:24px;color:#8DC892;filter:url(#leaf-glow)"
                        ></ha-icon>
                        <div class="tile-content">
                            <span class="tile-label">${this._t("carbon_avoided_today")}</span>
                            <span class="tile-hero" style="color:#8DC892">${s}</span>
                            <span class="tile-detail">${i}</span>
                        </div>
                    </div>

                    <!-- Right tile: Trees Equivalent -->
                    <div class="tile">
                        <ha-icon
                            icon="${d}"
                            style="--mdc-icon-size:24px;color:#8DC892;filter:url(#leaf-glow)"
                        ></ha-icon>
                        <div class="tile-content">
                            <span class="tile-label">${this._t("trees_equivalent")}</span>
                            <span class="tile-hero" style="color:#8DC892">${c}</span>
                            <div class="stats">
                                <div class="stat">
                                    <span class="stat-val">${l(n,"yearly_co2_avoided")}</span>
                                    <span class="stat-lbl">${this._t("co2_yearly")}</span>
                                </div>
                                <div class="stat">
                                    <span class="stat-val">${l(o,"lifetime_co2_avoided")}</span>
                                    <span class="stat-lbl">${this._t("co2_lifetime")}</span>
                                </div>
                                <div class="stat">
                                    <span class="stat-val">${null==a?Nt:a.toFixed(0)}</span>
                                    <span class="stat-lbl">${this._t("trees_lifetime")}</span>
                                </div>
                            </div>
                        </div>
                    </div>

                </div>
            </div>
        `}getCardSize(){return 3}static getStubConfig(){return{entity_prefix:Jt}}},{type:"sem-energy-impact-card",name:"SEM Energy Impact Card",description:"CO2 avoided and its tree equivalent — today, this year, lifetime",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-energy-impact-card",preview:!1});const se="daily_ev_energy",ie="lifetime_ev_energy",re="lifetime_ev_solar_share",ae="lifetime_ev_cost",ne="lifetime_ev_sessions",oe="sensor.sem_";kt("sem-ev-progress-card",class extends Lt{static get watchedEntities(){return[`${oe}${se}`,`${oe}${ie}`,`${oe}${re}`,`${oe}${ae}`,`${oe}${ne}`,"number.sem_daily_ev_target","number.sem_charger_ev_charger_daily_ev_target"]}_evDailyTarget(){const t=this._hass?.states||{},e=Object.keys(t).filter(t=>/^number\.sem_charger_.+_daily_ev_target$/.test(t)).sort();if(e.length){const s=parseFloat(t[e[0]]?.state);if(!isNaN(s))return s}return this._state("number.sem_daily_ev_target",10)}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix??oe}_pct(t,e){return null==t?null:e<=0?0:Math.min(100,t/e*100)}_barColor(t,e){return 0===t?"#666":e>=100?"#8DC892":e>=70?"#ff9800":"#f44336"}_fmtEnergy(t){return null==t||isNaN(t)?"—":t.toFixed(t<10?2:1)+" kWh"}_fmtCost(t,e){return null==t||isNaN(t)?"—":t.toFixed(2)+" "+e}_fmtSessions(t){return null==t||isNaN(t)?"—":String(Math.round(t))}render(){if(!this._hass||!this._config)return K;const t=this._theme(),e=this._prefix,s=this._state(`${e}${se}`),i=this._evDailyTarget(),r=this._state(`${e}${ie}`),a=this._state(`${e}${re}`),n=this._state(`${e}${ae}`),o=this._state(`${e}${ne}`),l=ft(this._hass),c=this._pct(s,i),d=this._barColor(i,c),p=i>0?H`<span class="target-pct">${Tt(c,0)}% ${this._t("of_target")}</span>`:H`<span class="target-pct no-target">${this._t("no_target")}</span>`,_=["radial-gradient(ellipse 80% 70% at 20% 50%, rgba(141,200,146,0.06) 0%, transparent 70%)",`radial-gradient(circle at 2px 2px, ${t.dotColor} 0.7px, transparent 0.7px)`].join(", ");return H`
            <style>
                :host {
                    display: block;
                    font-family: 'Segoe UI', 'Roboto', sans-serif;
                }

                .card {
                    background: ${t.cardBg};
                    background-image: ${_};
                    background-size: auto, 16px 16px;
                    border-radius: 12px;
                    padding: 16px;
                    box-shadow: ${t.shadow};
                    color: ${t.text};
                }

                /* ── Progress section ── */
                .progress-header {
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    margin-bottom: 10px;
                }

                .ev-icon {
                    font-size: 22px;
                    color: #8DC892;
                    flex-shrink: 0;
                    display: flex;
                    align-items: center;
                }

                .ev-icon ha-icon {
                    --mdc-icon-size: 22px;
                    color: #8DC892;
                }

                .progress-info {
                    flex: 1;
                    min-width: 0;
                }

                .progress-label {
                    font-size: 13px;
                    font-weight: 600;
                    color: ${t.text};
                    letter-spacing: 0.3px;
                }

                .progress-values {
                    font-size: 12px;
                    color: ${t.textSec};
                    margin-top: 2px;
                }

                .target-pct {
                    font-size: 11px;
                    color: ${t.textSec};
                    margin-top: 1px;
                    display: block;
                }

                .no-target {
                    opacity: 0.6;
                    font-style: italic;
                }

                /* ── Progress bar ── */
                .progress-track {
                    height: 6px;
                    border-radius: 3px;
                    background: ${t.surface};
                    border: 1px solid ${t.surfaceBorder};
                    overflow: hidden;
                    margin-top: 10px;
                }

                .progress-fill {
                    height: 100%;
                    border-radius: 3px;
                    transition: width 0.5s ease, background 0.3s ease;
                }

                /* ── Section divider ── */
                .divider {
                    height: 1px;
                    background: ${t.divider};
                    margin: 14px 0;
                }

                /* ── Lifetime stats section ── */
                .lifetime-label {
                    font-size: 11px;
                    font-weight: 600;
                    text-transform: uppercase;
                    letter-spacing: 1px;
                    color: ${t.textSec};
                    margin-bottom: 10px;
                }

                .stats-grid {
                    display: grid;
                    grid-template-columns: 1fr 1fr 1fr 1fr;
                    gap: 8px;
                }

                @media (max-width: 400px) {
                    .stats-grid {
                        grid-template-columns: 1fr 1fr;
                    }
                }

                .stat-tile {
                    background: ${t.surface};
                    border: 1px solid ${t.surfaceBorder};
                    border-radius: 8px;
                    padding: 10px 8px;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    gap: 4px;
                    text-align: center;
                }

                .stat-icon ha-icon {
                    --mdc-icon-size: 18px;
                    color: #8DC892;
                }

                .stat-value {
                    font-size: 13px;
                    font-weight: 700;
                    color: ${t.text};
                    line-height: 1.2;
                }

                .stat-label {
                    font-size: 11px;
                    color: ${t.textSec};
                    letter-spacing: 0.3px;
                    line-height: 1.2;
                }
            </style>

            <div class="card">
                <!-- Progress section -->
                <div class="progress-header">
                    <div class="ev-icon">
                        <ha-icon icon="mdi:car-electric"></ha-icon>
                    </div>
                    <div class="progress-info">
                        <div class="progress-label">${this._t("daily_progress")}</div>
                        <div class="progress-values">
                            ${this._fmtEnergy(s)}${i>0?` / ${this._fmtEnergy(i)}`:""}
                        </div>
                        ${p}
                    </div>
                </div>

                <div class="progress-track">
                    <div
                        class="progress-fill"
                        style="width:${c??0}%;background:${d}"
                    ></div>
                </div>

                <div class="divider"></div>

                <!-- Lifetime stats section -->
                <div class="lifetime-label">${this._t("lifetime_stats")}</div>
                <div class="stats-grid">
                    <div class="stat-tile">
                        <div class="stat-icon"><ha-icon icon="mdi:lightning-bolt"></ha-icon></div>
                        <div class="stat-value">${this._fmtEnergy(r)}</div>
                        <div class="stat-label">${this._t("energy")}</div>
                    </div>
                    <div class="stat-tile">
                        <div class="stat-icon"><ha-icon icon="mdi:weather-sunny"></ha-icon></div>
                        <div class="stat-value">${Tt(a,0)}%</div>
                        <div class="stat-label">${this._t("solar")}</div>
                    </div>
                    <div class="stat-tile">
                        <div class="stat-icon"><ha-icon icon="mdi:currency-usd"></ha-icon></div>
                        <div class="stat-value">${this._fmtCost(n,l)}</div>
                        <div class="stat-label">${this._t("cost")}</div>
                    </div>
                    <div class="stat-tile">
                        <div class="stat-icon"><ha-icon icon="mdi:counter"></ha-icon></div>
                        <div class="stat-value">${this._fmtSessions(o)}</div>
                        <div class="stat-label">${this._t("sessions")}</div>
                    </div>
                </div>
            </div>
        `}getCardSize(){return 3}static getStubConfig(){return{entity_prefix:oe}}},{type:"sem-ev-progress-card",name:"SEM EV Progress Card",description:"Daily EV progress bar and lifetime charging statistics",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-ev-progress-card"});kt("sem-gauge-card",class extends Lt{static get watchedEntities(){return[]}setConfig(t){if(!t.entity)throw new Error("sem-gauge-card requires entity");super.setConfig(t),this._entity=t.entity,this._name=t.name||null,this._min=t.min??0,this._max=t.max??100,this._color=t.color||"#4db6ac",this._unit=t.unit||"%"}set hass(t){this._hass,this._hass=t;const e=t?.states[this._entity]?.state;e!==this._lastState&&(this._lastState=e,this.requestUpdate())}get hass(){return this._hass}render(){if(!this._hass||!this._config)return K;const t=this._hass.states[this._entity],e=At(t),s=this._name||t?.attributes?.friendly_name||this._entity,i=null==e?0:Math.min(Math.max((e-this._min)/(this._max-this._min),0),1),r=this._theme(),a=this._color,n=58,o=-210,l=o+240*i,c=t=>{const e=t*Math.PI/180;return{x:70+n*Math.cos(e),y:70+n*Math.sin(e)}},d=c(o),p=c(30),_=c(l),h=240*i>180?1:0,u=i<.5?`color-mix(in srgb, #f44336 ${Math.round(100*(1-2*i))}%, #ff9800)`:`color-mix(in srgb, ${a} ${Math.round(2*(i-.5)*100)}%, #ff9800)`;return H`
            <ha-card>
                <div class="gauge-wrap">
                    <svg viewBox="0 0 140 100" xmlns="http://www.w3.org/2000/svg">
                        <defs>
                            <filter id="glow-${this._entity.replace(/\./g,"_")}" x="-20%" y="-20%" width="140%" height="140%">
                                <feGaussianBlur stdDeviation="3" result="blur"/>
                                <feFlood flood-color="${u}" flood-opacity="0.3"/>
                                <feComposite in2="blur" operator="in"/>
                                <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
                            </filter>
                        </defs>
                        <!-- Background arc -->
                        <path d="M ${d.x} ${d.y} A ${n} ${n} 0 ${1} 1 ${p.x} ${p.y}"
                              fill="none" stroke="${r.surface||"rgba(255,255,255,0.08)"}" stroke-width="8"
                              stroke-linecap="round"/>
                        <!-- Value arc -->
                        ${i>.01?j`
                            <path d="M ${d.x} ${d.y} A ${n} ${n} 0 ${h} 1 ${_.x} ${_.y}"
                                  fill="none" stroke="${u}" stroke-width="8"
                                  stroke-linecap="round"
                                  filter="url(#glow-${this._entity.replace(/\./g,"_")})"
                                  style="transition: d 1s ease"/>
                        `:""}
                    </svg>
                    <div class="gauge-center">
                        <span class="gauge-value" style="color:${u}">${Tt(e,1)}${this._unit}</span>
                    </div>
                    <div class="gauge-label">${s}</div>
                </div>
            </ha-card>
        `}static get styles(){return a`
            :host { display: block; }
            ha-card {
                background: transparent !important;
                border: none !important;
                box-shadow: none !important;
            }
            .gauge-wrap {
                position: relative;
                display: flex;
                flex-direction: column;
                align-items: center;
                padding: 16px 16px 8px;
            }
            svg {
                width: 180px;
                height: 130px;
            }
            .gauge-center {
                position: absolute;
                top: 65px;
                left: 50%;
                transform: translateX(-50%);
                text-align: center;
            }
            .gauge-value {
                font-size: 28px;
                font-weight: 700;
                font-variant-numeric: tabular-nums;
                font-family: 'Segoe UI', 'Roboto', sans-serif;
            }
            .gauge-label {
                font-size: 13px;
                font-weight: 500;
                color: var(--secondary-text-color, #9e9e9e);
                text-align: center;
                margin-top: -8px;
                font-family: 'Segoe UI', 'Roboto', sans-serif;
            }
        `}getCardSize(){return 3}static getStubConfig(){return{entity:"sensor.sem_self_consumption_rate"}}},{type:"sem-gauge-card",name:"SEM Gauge Card",description:"Lumina-styled arc gauge for percentage values",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-gauge-card",preview:!1});const le="sensor.sem_",ce=["solar_power","daily_solar_energy","monthly_solar_yield_energy","yearly_solar_yield_energy","flow_solar_to_home_power","flow_solar_to_battery_power","flow_solar_to_ev_power","flow_solar_to_grid_power","flow_solar_to_home_energy","flow_solar_to_battery_energy","flow_solar_to_ev_energy","flow_solar_to_grid_energy","forecast_today_kwh","forecast_tomorrow_kwh","forecast_remaining_today_kwh","forecast_peak_power_today_w","forecast_peak_time_today","forecast_peak_power_path","best_surplus_window","pv_daily_specific_yield","pv_performance_vs_forecast","pv_estimated_annual_degradation","pv_degradation_trend","pv_string_pv1_power","pv_string_pv1_daily_energy","pv_string_pv2_power","pv_string_pv2_daily_energy","pv_string_pv3_power","pv_string_pv3_daily_energy","pv_string_pv4_power","pv_string_pv4_daily_energy"];function de(t){return ce.map(e=>`${t}${e}`)}kt("sem-solar-card",class extends Lt{static get styles(){return[Ot]}static get watchedEntities(){return de(le)}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||le,this._prefix!==le&&(this._prevVals={})}set hass(t){this._hass=t;const e=t?.language,s="function"==typeof semLocalize;let i=!1;if((e!==this._lang||s&&!this._localizeReady)&&(this._lang=e,this._localizeReady=s,i=!0),this._isFrozen()&&!i)return;const r=de(this._prefix||le);let a=!1;for(const e of r)if(this._prevVals[e]!==t.states[e]?.state){a=!0;break}if(a||i){for(const e of r)this._prevVals[e]=t.states[e]?.state;this._scheduleUpdate()}}get hass(){return this._hass}_val(t,e=null){return this._state(`${this._prefix}${t}`,e)}_valStr(t){return this._stateStr(`${this._prefix}${t}`)}_fmt(t,e=1){return null==t||isNaN(t)?"—":t.toFixed(e)}render(){if(!this._config)return K;const t=this._theme(),e=this._val("solar_power"),s=this._val("daily_solar_energy"),i=this._val("monthly_solar_yield_energy"),r=this._val("yearly_solar_yield_energy"),a=Math.min(Math.max(e/1e4,0),1),n=2*Math.PI*42,o=(n*(1-a)).toFixed(1),l=e>50?"solarPulse 3s ease-in-out infinite":"none",c=this._val("flow_solar_to_home_power"),d=this._val("flow_solar_to_home_energy"),p=this._val("flow_solar_to_battery_power"),_=this._val("flow_solar_to_battery_energy"),h=this._val("flow_solar_to_ev_power"),u=this._val("flow_solar_to_ev_energy"),g=this._val("flow_solar_to_grid_power"),m=this._val("flow_solar_to_grid_energy"),f=this._val("forecast_today_kwh"),y=this._val("forecast_tomorrow_kwh"),v=this._val("forecast_remaining_today_kwh"),b=this._val("forecast_peak_power_today_w"),x=this._valStr("forecast_peak_time_today"),$="unsupported_by_source"===this._valStr("forecast_peak_power_path")?this._t("peak_power_unsupported"):"",w=this._valStr("best_surplus_window"),k=this._val("pv_daily_specific_yield"),S=this._val("pv_performance_vs_forecast"),C=this._val("pv_estimated_annual_degradation"),z=this._valStr("pv_degradation_trend"),M=S?this._fmt(S,0)+"%":"—",D=S>=0?"#8DC892":"#f06292",E=xt(this._hass,this._prefix);return H`
            <style>
                :host { display: block; }
                .wrap {
                    padding: 16px 20px;
                    position: relative;
                    background: ${vt(t,pt.solar)};
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${t.text});
                }
                .glow-svg { position: absolute; width: 0; height: 0; overflow: hidden; }

                /* ── Hero ── */
                .hero { display: flex; align-items: center; gap: 20px; }
                @media (max-width: 400px) { .hero { flex-direction: column; gap: 12px; } }

                .solar-ring { position: relative; width: 100px; height: 100px; flex-shrink: 0; }
                .solar-ring svg { width: 100%; height: 100%; transform: rotate(-90deg); }
                .ring-bg { fill: none; stroke: rgba(255,152,0,0.12); stroke-width: 5; }
                .solar-arc {
                    fill: none; stroke: #ff9800; stroke-width: 5; stroke-linecap: round;
                    transition: stroke-dashoffset 1.5s cubic-bezier(0.4,0,0.2,1);
                    filter: url(#solar-glow);
                }
                .solar-glow-ring {
                    fill: none; stroke: #ff9800; stroke-width: 8; opacity: 0.2;
                    filter: url(#solar-glow-soft);
                }
                @keyframes solarPulse { 0%,100%{opacity:1}50%{opacity:0.6} }

                .ring-center {
                    position: absolute; top: 50%; left: 50%;
                    transform: translate(-50%, -50%);
                    text-align: center; pointer-events: none;
                }
                .solar-power-value {
                    font-size: 13px; font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    color: #ff9800;
                    text-shadow: 0 0 8px rgba(255,152,0,0.35);
                    line-height: 1.2;
                }
                .solar-daily-value {
                    font-size: 11px; color: var(--secondary-text-color,${t.textSec});
                    font-variant-numeric: tabular-nums;
                }

                /* ── Section ── */
                .section {
                    margin-top: 12px;
                    padding: 10px 12px;
                    background: var(--secondary-background-color, ${t.surface});
                    border: 1px solid var(--divider-color, ${t.surfaceBorder});
                    border-radius: 10px;
                }
                .section-title {
                    font-size: 12px; font-weight: 600; text-transform: uppercase;
                    letter-spacing: 0.6px; color: #ff9800; margin-bottom: 8px;
                }

                /* ── Flows grid ── */
                .flows-grid {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 8px 24px;
                }
                .flow-row { display: flex; align-items: center; gap: 6px; }
                .flow-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
                .flow-label { font-size: 12px; color: var(--secondary-text-color,${t.textSec}); flex: 1; }
                .flow-vals { text-align: right; }
                .flow-power {
                    font-size: 13px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color,${t.text});
                }
                .flow-energy {
                    font-size: 11px; color: var(--secondary-text-color,${t.textSec});
                    font-variant-numeric: tabular-nums;
                }

                /* ── Two-column section ── */
                .two-col {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 0 20px;
                }
                @media (max-width: 400px) { .two-col { grid-template-columns: 1fr; } }

                /* Mobile polish (added during the same fix as the
                   render-bug repair): the existing 400px breakpoints
                   only handle the very narrowest phones. The card is
                   noticeably cramped on a typical 375–480px viewport
                   without these — the 2-col flows grid produces two
                   ~155px columns of dense kWh data. */
                @media (max-width: 480px) {
                    .hero { flex-direction: column; gap: 12px; align-items: stretch; }
                    .solar-ring { width: 90px; height: 90px; margin: 0 auto; }
                    .flows-grid { grid-template-columns: 1fr; gap: 6px; }
                    .section { padding: 8px 10px; margin-top: 10px; }
                    .metric-row { padding: 1px 0; }
                    .chip { padding: 5px 6px; }
                    .chip-value { font-size: 12px; }
                }

                /* ── Metric rows ── */
                .metric-row {
                    display: flex; justify-content: space-between; align-items: baseline;
                    padding: 2px 0;
                }
                .metric-label {
                    font-size: 12px; color: var(--secondary-text-color,${t.textSec});
                    font-weight: 500;
                }
                .metric-val {
                    font-size: 13px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color,${t.text});
                }

                /* ── Monthly / yearly chips ── */
                .chips { display: flex; gap: 8px; margin-top: 10px; }
                .chip {
                    flex: 1; text-align: center; padding: 7px 8px;
                    background: var(--secondary-background-color, ${t.surface});
                    border: 1px solid var(--divider-color, ${t.surfaceBorder});
                    border-radius: 10px;
                }
                .chip-label {
                    font-size: 12px; color: var(--secondary-text-color,${t.textTertiary});
                    font-weight: 500; margin-bottom: 2px;
                }
                .chip-value {
                    font-size: 14px; font-weight: 600; color: #ff9800;
                    font-variant-numeric: tabular-nums;
                }
                /* v1.7.1 / #312: per-PV-string chip strip styles */
                ${wt}
            </style>

            <!-- SVG glow filters -->
            <svg class="glow-svg" aria-hidden="true">
                <defs>
                    <filter id="solar-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="4" result="blur"/>
                        <feFlood flood-color="#ff9800" flood-opacity="0.3" result="color"/>
                        <feComposite in="color" in2="blur" operator="in" result="glow"/>
                        <feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                    <filter id="solar-glow-soft" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="6" result="blur"/>
                        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                </defs>
            </svg>

            <ha-card>
                <div class="wrap">

                    <!-- v1.7.1 / #312: per-PV-string chip strip (auto-shown ≥ 2 strings) -->
                    ${E.length>=2?H`
                        <div class="pv-strings-row">
                            ${E.map(t=>H`
                                <div class="pv-chip"
                                     title="${t.entityId}"
                                     data-entity="${t.entityId}"
                                     @click=${()=>this._fireMoreInfo(t.entityId)}>
                                    <span class="pv-chip-label">${t.name}</span>
                                    <span class="pv-chip-value">${$t(t.watts)}</span>
                                </div>
                            `)}
                        </div>
                    `:K}

                    <!-- Hero -->
                    <div class="hero">
                        <div class="solar-ring">
                            <svg viewBox="0 0 100 100">
                                <circle class="solar-glow-ring" cx="50" cy="50" r="42">
                                    <animate attributeName="opacity" values="0.2;0.07;0.2" dur="4s" repeatCount="indefinite"/>
                                </circle>
                                <circle class="ring-bg" cx="50" cy="50" r="42"/>
                                <circle class="solar-arc" cx="50" cy="50" r="42"
                                    stroke-dasharray="${n.toFixed(1)}"
                                    style="stroke-dashoffset:${o};animation:${l}"/>
                            </svg>
                            <div class="ring-center">
                                <ha-icon icon="mdi:solar-power" style="--mdc-icon-size:22px;color:#ff9800;opacity:0.8"></ha-icon>
                                <div class="solar-power-value">${ut(e)}</div>
                                <div class="solar-daily-value">${this._fmt(s,2)} kWh</div>
                            </div>
                        </div>

                        <!-- Monthly + Yearly chips -->
                        <div style="flex:1;min-width:0">
                            <div class="chips" style="margin-top:0">
                                <div class="chip">
                                    <div class="chip-label">${this._t("monthly")}</div>
                                    <div class="chip-value">${this._fmt(i,1)} kWh</div>
                                </div>
                                <div class="chip">
                                    <div class="chip-label">${this._t("yearly")}</div>
                                    <div class="chip-value">${this._fmt(r,1)} kWh</div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Today's Flows -->
                    <div class="section">
                        <div class="section-title">${this._t("solar_flows_today")}</div>
                        <div class="flows-grid">
                            <div class="flow-row">
                                <div class="flow-dot" style="background:#5BC8D8"></div>
                                <span class="flow-label">${this._t("home")}</span>
                                <div class="flow-vals">
                                    <div class="flow-power">${ut(c)}</div>
                                    <div class="flow-energy">${this._fmt(d,2)} kWh</div>
                                </div>
                            </div>
                            <div class="flow-row">
                                <div class="flow-dot" style="background:#f06292"></div>
                                <span class="flow-label">${this._t("battery")}</span>
                                <div class="flow-vals">
                                    <div class="flow-power">${ut(p)}</div>
                                    <div class="flow-energy">${this._fmt(_,2)} kWh</div>
                                </div>
                            </div>
                            <div class="flow-row">
                                <div class="flow-dot" style="background:#8DC892"></div>
                                <span class="flow-label">${this._t("ev")}</span>
                                <div class="flow-vals">
                                    <div class="flow-power">${ut(h)}</div>
                                    <div class="flow-energy">${this._fmt(u,2)} kWh</div>
                                </div>
                            </div>
                            <div class="flow-row">
                                <div class="flow-dot" style="background:#8353d1"></div>
                                <span class="flow-label">${this._t("grid_export")}</span>
                                <div class="flow-vals">
                                    <div class="flow-power">${ut(g)}</div>
                                    <div class="flow-energy">${this._fmt(m,2)} kWh</div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- v1.7.0 / #312: per-PV-string detail. Reuses
                         the "flow row" style for visual consistency
                         with the Today's Flows section above. Auto-
                         shown when 2+ strings are present; collapses
                         to nothing on single-string installs.
                         (Do NOT quote "nothing" with backticks here;
                         this HTML comment lives inside an html
                         tagged template literal, and a stray
                         backtick terminates that template at parse
                         time — see the 0x0 render bug we fixed.) -->
                    ${E.length>=2?H`
                        <div class="section">
                            <div class="section-title">${this._t("pv_strings_today")||"Per string today"}</div>
                            <div class="flows-grid">
                                ${E.map(t=>H`
                                    <div class="flow-row"
                                         style="cursor:pointer"
                                         @click=${()=>this._fireMoreInfo(t.entityId)}>
                                        <div class="flow-dot" style="background:#ff9800"></div>
                                        <span class="flow-label">${t.name}</span>
                                        <div class="flow-vals">
                                            <div class="flow-power">${ut(t.watts)}</div>
                                            <div class="flow-energy">${null!=t.energyKwh?this._fmt(t.energyKwh,2)+" kWh":"—"}</div>
                                        </div>
                                    </div>
                                `)}
                            </div>
                        </div>
                    `:K}

                    <!-- Forecast + Performance (side by side) -->
                    <div class="section two-col">
                        <div>
                            <div class="section-title">${this._t("forecast")}</div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("today")}</span>
                                <span class="metric-val">${this._fmt(f,1)} kWh</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("tomorrow")}</span>
                                <span class="metric-val">${this._fmt(y,1)} kWh</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("remaining")}</span>
                                <span class="metric-val">${this._fmt(v,1)} kWh</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("peak_power")}</span>
                                <span class="metric-val" title="${$}">
                                    ${b>0?ut(b):"—"}
                                    <span style="font-size:11px;opacity:0.7;margin-left:4px">${x||"—"}</span>
                                </span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("best_surplus_window")}</span>
                                <span class="metric-val" style="color:#ff9800;font-size:11px">${w||"—"}</span>
                            </div>
                        </div>
                        <div>
                            <div class="section-title">${this._t("performance")}</div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("specific_yield")}</span>
                                <span class="metric-val">${k>0?this._fmt(k,2)+" kWh/kWp":"—"}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("vs_forecast")}</span>
                                <span class="metric-val" style="color:${D}">${M}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("degradation")}</span>
                                <span class="metric-val">${C?this._fmt(C,2)+"%/yr":"—"}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("trend")}</span>
                                <span class="metric-val">${z?this._t(z):"—"}</span>
                            </div>
                        </div>
                    </div>

                </div>
            </ha-card>
        `}getCardSize(){return 5}static getStubConfig(){return{entity_prefix:le}}},{type:"sem-solar-card",name:"SEM Solar",description:"Consolidated solar production card with flows, forecast, and performance metrics",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-solar-card"});const pe=["sensor.sem_daily_solar_energy","sensor.sem_solar_power"];kt("sem-solar-kpi-card",class extends Lt{static get watchedEntities(){return pe}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||"sensor.sem_"}_val(t,e=null){return At(this._hass?.states[`${this._prefix}${t}`])??e}static get styles(){return a`
                :host { display: block; }
                .kpi {
                    display: flex;
                    align-items: center;
                    gap: 18px;
                    padding: 18px 22px;
                }
                .kpi-icon {
                    flex: 0 0 auto;
                    width: 52px;
                    height: 52px;
                    border-radius: 14px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    background: rgba(255, 152, 0, 0.14);
                }
                .kpi-icon ha-icon {
                    color: #ff9800;
                    --mdc-icon-size: 32px;
                }
                .kpi-main { flex: 1 1 auto; min-width: 0; }
                .kpi-value {
                    font-size: 2.6rem;
                    font-weight: 700;
                    line-height: 1.1;
                    color: #ff9800;
                    letter-spacing: -0.5px;
                    white-space: nowrap;
                }
                .kpi-value .unit {
                    font-size: 1.3rem;
                    font-weight: 500;
                    opacity: 0.85;
                    margin-left: 4px;
                }
                .kpi-label {
                    margin-top: 2px;
                    font-size: 0.85rem;
                    color: var(--secondary-text-color);
                    text-transform: uppercase;
                    letter-spacing: 0.6px;
                }
                .kpi-now {
                    flex: 0 0 auto;
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    padding: 6px 12px;
                    border-radius: 999px;
                    background: var(--secondary-background-color, rgba(255,255,255,0.06));
                    font-size: 0.9rem;
                    color: var(--primary-text-color);
                }
                .kpi-now ha-icon {
                    color: #ff9800;
                    --mdc-icon-size: 16px;
                }
                @media (max-width: 460px) {
                    .kpi { padding: 14px 16px; gap: 12px; }
                    .kpi-value { font-size: 2.1rem; }
                    .kpi-icon { width: 44px; height: 44px; }
                }
            `}render(){if(!this._hass)return K;const t=this._val("daily_solar_energy"),e=this._val("solar_power");return H`
            <ha-card>
                <div class="kpi">
                    <div class="kpi-icon"><ha-icon icon="mdi:solar-power-variant"></ha-icon></div>
                    <div class="kpi-main">
                        <div class="kpi-value">${Tt(t,1)}<span class="unit">kWh</span></div>
                        <div class="kpi-label">${this._t("todays_solar_production")}</div>
                    </div>
                    ${e>0?H`
                        <div class="kpi-now">
                            <ha-icon icon="mdi:white-balance-sunny"></ha-icon>
                            <span>${ut(e)}</span>
                        </div>
                    `:K}
                </div>
            </ha-card>
        `}getCardSize(){return 1}static getStubConfig(){return{}}},{type:"sem-solar-kpi-card",name:"SEM Solar KPI Card",description:"Prominent Today's Solar Production KPI for the Home tab",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-solar-kpi-card",preview:!0});const _e="sensor.sem_",he=["solar_power","daily_solar_energy","monthly_solar_yield_energy","forecast_today_kwh","forecast_tomorrow_kwh","self_consumption_rate","autarky_rate","daily_costs","daily_savings","daily_ev_energy","daily_grid_import_energy"];function ue(t){return he.map(e=>`${t}${e}`)}kt("sem-solar-summary-card",class extends Lt{static get watchedEntities(){return ue(_e)}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||_e,this._prefix!==_e&&(this._prevVals={})}set hass(t){this._hass=t;const e=t?.language,s="function"==typeof semLocalize;let i=!1;if((e!==this._lang||s&&!this._localizeReady)&&(this._lang=e,this._localizeReady=s,i=!0),this._isFrozen()&&!i)return;const r=ue(this._prefix||_e);let a=!1;for(const e of r)if(this._prevVals[e]!==t.states[e]?.state){a=!0;break}if(a||i){for(const e of r)this._prevVals[e]=t.states[e]?.state;this._scheduleUpdate()}}get hass(){return this._hass}_val(t,e=null){return this._state(`${this._prefix}${t}`,e)}_valStr(t){return this._stateStr(`${this._prefix}${t}`)}_fmt(t,e=1){return null==t||isNaN(t)?"—":t.toFixed(e)}render(){if(!this._config)return K;const t=this._theme(),e=this._val("solar_power"),s=this._val("daily_solar_energy"),i=this._val("monthly_solar_yield_energy"),r=this._val("forecast_today_kwh"),a=this._val("forecast_tomorrow_kwh"),n=this._val("self_consumption_rate"),o=this._val("autarky_rate"),l=this._val("daily_costs"),c=this._val("daily_savings"),d=this._val("daily_ev_energy"),p=this._val("daily_grid_import_energy"),_=ft(this._hass),h=(.15+.6*Math.min(e/1e4,1)).toFixed(3),u=2*Math.PI*42,g=(u*(1-(r>0?Math.min(s/r,1):0))).toFixed(1);return H`
            <style>
                :host { display: block; }
                .wrap {
                    padding: 16px 20px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 25%, rgba(255,152,0,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${t.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${t.text});
                }
                .glow-svg { position: absolute; width: 0; height: 0; overflow: hidden; }

                /* Hero section */
                .hero {
                    display: flex;
                    align-items: center;
                    gap: 20px;
                    margin-bottom: 20px;
                }
                .solar-ring {
                    position: relative;
                    width: 100px;
                    height: 100px;
                    flex-shrink: 0;
                }
                .solar-ring svg {
                    width: 100%;
                    height: 100%;
                    transform: rotate(-90deg);
                }
                .ring-bg {
                    fill: none;
                    stroke: rgba(255,152,0,0.12);
                    stroke-width: 5;
                }
                .progress-arc {
                    fill: none;
                    stroke: #ff9800;
                    stroke-width: 5;
                    stroke-linecap: round;
                    transition: stroke-dashoffset 1.5s cubic-bezier(0.4,0,0.2,1);
                    filter: url(#solar-glow);
                }
                .ring-icon {
                    position: absolute;
                    top: 50%;
                    left: 50%;
                    transform: translate(-50%, -50%);
                    text-align: center;
                }
                .ring-icon .power {
                    font-size: 18px;
                    font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    color: #ff9800;
                    text-shadow: 0 0 8px rgba(255,152,0,0.3);
                }
                .ring-icon .label {
                    font-size: 11px;
                    color: rgba(255,152,0,0.6);
                    font-weight: 500;
                    letter-spacing: 1px;
                    text-transform: uppercase;
                }
                .hero-stats {
                    flex: 1;
                    min-width: 0;
                }
                .hero-title {
                    font-size: 13px;
                    font-weight: 600;
                    color: rgba(255,152,0,0.85);
                    letter-spacing: 0.5px;
                    margin-bottom: 8px;
                }
                .hero-row {
                    display: flex;
                    justify-content: space-between;
                    align-items: baseline;
                    padding: 3px 0;
                }
                .hero-label {
                    font-size: 12px;
                    color: var(--secondary-text-color, ${t.textSec});
                    font-weight: 500;
                }
                .hero-value {
                    font-size: 13px;
                    font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }

                /* Metrics grid */
                .metrics {
                    display: grid;
                    grid-template-columns: repeat(3, 1fr);
                    gap: 10px;
                }
                .metric {
                    background: var(--secondary-background-color, ${t.surface});
                    border: 1px solid var(--divider-color, ${t.surfaceBorder});
                    border-radius: 10px;
                    padding: 10px;
                    text-align: center;
                    transition: border-color 0.3s cubic-bezier(0.4,0,0.2,1);
                }
                .metric:hover {
                    border-color: var(--divider-color, ${t.surfaceHover});
                }
                .metric-label {
                    font-size: 11px;
                    color: var(--secondary-text-color, ${t.textTertiary});
                    font-weight: 500;
                    letter-spacing: 0.3px;
                    margin-bottom: 4px;
                }
                .metric-value {
                    font-size: 14px;
                    font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }
                .c-solar   { color: #ff9800; }
                .c-grid    { color: #488fc2; }
                .c-ev      { color: #8DC892; }
                .c-home    { color: #5BC8D8; }
                .c-savings { color: #4db6ac; }
                .c-cost    { color: #f06292; }
            </style>

            <!-- SVG glow filters -->
            <svg class="glow-svg" aria-hidden="true">
                <defs>
                    <filter id="solar-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="3" result="blur"/>
                        <feFlood flood-color="#ff9800" flood-opacity="0.25" result="color"/>
                        <feComposite in="color" in2="blur" operator="in" result="glow"/>
                        <feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                    <filter id="solar-glow-soft" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="6" result="blur"/>
                        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                </defs>
            </svg>

            <ha-card>
                <div class="wrap">

                    <!-- Hero -->
                    <div class="hero">
                        <div class="solar-ring">
                            <svg viewBox="0 0 100 100">
                                <circle cx="50" cy="50" r="42"
                                    fill="none" stroke="#ff9800" stroke-width="8"
                                    filter="url(#solar-glow-soft)"
                                    style="opacity:${h}">
                                    <animate attributeName="r" values="42;45;42" dur="3s" repeatCount="indefinite"/>
                                    <animate attributeName="opacity" values="${h};${(.4*parseFloat(h)).toFixed(3)};${h}" dur="3s" repeatCount="indefinite"/>
                                </circle>
                                <circle class="ring-bg" cx="50" cy="50" r="42"/>
                                <circle class="progress-arc" cx="50" cy="50" r="42"
                                    stroke-dasharray="${u.toFixed(1)}"
                                    style="stroke-dashoffset:${g}"/>
                            </svg>
                            <div class="ring-icon">
                                <div class="power">${ut(e)}</div>
                                <div class="label">${this._t("solar").toUpperCase()}</div>
                            </div>
                        </div>

                        <div class="hero-stats">
                            <div class="hero-title">${this._t("production")}</div>
                            <div class="hero-row">
                                <span class="hero-label">${this._t("yield_today")}</span>
                                <span class="hero-value c-solar">${this._fmt(s,2)} kWh</span>
                            </div>
                            <div class="hero-row">
                                <span class="hero-label">${this._t("grid_today")}</span>
                                <span class="hero-value c-grid">${this._fmt(p,2)} kWh</span>
                            </div>
                            <div class="hero-row">
                                <span class="hero-label">${this._t("forecast")}</span>
                                <span class="hero-value c-solar">${this._fmt(r,1)} kWh</span>
                            </div>
                            <div class="hero-row">
                                <span class="hero-label">${this._t("tomorrow")}</span>
                                <span class="hero-value" style="color:var(--secondary-text-color)">${this._fmt(a,1)} kWh</span>
                            </div>
                        </div>
                    </div>

                    <!-- Metrics 3x2 grid -->
                    <div class="metrics">
                        <div class="metric">
                            <div class="metric-label">${this._t("self_use")}</div>
                            <div class="metric-value c-home">${this._fmt(n,1)}%</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">${this._t("autarky")}</div>
                            <div class="metric-value c-savings">${this._fmt(o,1)}%</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">${this._t("ev_today")}</div>
                            <div class="metric-value c-ev">${this._fmt(d,1)} kWh</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">${this._t("cost")}</div>
                            <div class="metric-value c-cost">${this._fmt(l,2)} ${_}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">${this._t("saved")}</div>
                            <div class="metric-value c-savings">${this._fmt(c,2)} ${_}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">${this._t("monthly")}</div>
                            <div class="metric-value c-solar">${this._fmt(i,1)} kWh</div>
                        </div>
                    </div>

                </div>
            </ha-card>
        `}getCardSize(){return 4}static getStubConfig(){return{entity_prefix:_e}}},{type:"sem-solar-summary-card",name:"SEM Solar Summary",description:"Lumina-styled solar overview with glow ring and production metrics",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-solar-summary-card"});const ge={solcast:"Solcast",forecast_solar:"Forecast.Solar",open_meteo:"Open-Meteo",helios:"Helios"};function me(t,e,s){const i=function(t){if(!t||"string"!=typeof t)return null;const e=t.trim().toLowerCase();return e&&"unknown"!==e&&"unavailable"!==e&&"none"!==e?ge[e]||e.replace(/_/g," "):null}(t),r=s(1===e?"horizon_tomorrow":"horizon_two_days");return i?`${i} · ${r}`:`${s("forecast_accuracy")} · ${r}`}function fe({measuredKwh:t,nameplateKwh:e,t:s}){if(null==t)return s("capacity_using_nameplate");if(null==e)return s("capacity_using_measured");const i=t-e;return Math.abs(i)<.05?s("capacity_matches_nameplate"):s("capacity_using_measured")}const ye="sensor.sem_",ve=["battery_soc","battery_power","battery_charge_power","battery_discharge_power","battery_status","battery_health_score","battery_cycles_estimated","battery_temperature","battery_session_type","battery_session_energy","battery_session_solar_share","battery_session_duration","battery_session_avg_power","battery_session_cost","battery_session_savings","daily_battery_charge_energy","daily_battery_discharge_energy","daily_battery_savings","flow_solar_to_battery_energy","flow_grid_to_battery_energy","monthly_battery_charge_energy","monthly_battery_discharge_energy","battery_spendable_kwh","forecast_source"],be=["#4db6ac","#FFB74D","#BA68C8","#64B5F6"];kt("sem-battery-card",class extends Lt{constructor(){super(),this._batteries=[],this._lastStateCount=0}static get watchedEntities(){return ve.map(t=>`${ye}${t}`)}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||ye}set hass(t){this._hass=t;const e=t?.language,s="function"==typeof semLocalize;let i=!1;(e!==this._lang||s&&!this._localizeReady)&&(this._lang=e,this._localizeReady=s,i=!0);const r=Object.keys(t.states).length;if(r!==this._lastStateCount){this._lastStateCount=r;const e=[];for(const s of Object.keys(t.states)){const t=s.match(/^sensor\.sem_battery_(b\d+)_power$/);t&&e.push(t[1])}e.sort(),this._batteries=e}if(this._isFrozen()&&!i)return;const a=ve.map(t=>`${this._prefix}${t}`);for(const t of this._batteries)a.push(`${this._prefix}battery_${t}_power`,`${this._prefix}battery_${t}_soc`);if(!i&&Rt(t?.states,a))return;let n=ve.map(e=>t?.states[`${this._prefix}${e}`]?.state||"").join(",")+"|"+e;this._batteries.length?n+="|"+this._batteries.map(e=>{const s=[`battery_${e}_power`,`battery_${e}_soc`,`battery_${e}_status`,`battery_${e}_capacity_kwh`].map(e=>t?.states[`${this._prefix}${e}`]?.state||"").join(":"),i=[`select.sem_battery_${e}_mode`,`number.sem_battery_${e}_reserve_soc`].map(e=>t?.states[e]?.state||"").join(":");return s+":"+i}).join("|"):n+="|"+["select.sem_battery_mode","number.sem_battery_reserve_soc"].map(e=>t?.states[e]?.state||"").join(":"),(n!==this._lastBattKey||i)&&(this._lastBattKey=n,this._scheduleUpdate())}get hass(){return this._hass}_val(t,e=null){return this._state(`${this._prefix}${t}`,e)}_valStr(t){return this._stateStr(`${this._prefix}${t}`)}_renderPacingLine(){const t=this._hass?.states?.["sensor.sem_battery_charge_pacing"];if(!t||"unavailable"===t.state)return K;const e=t.attributes||{},s=e.reason_code||"none";if("none"===s||"night"===s)return K;const i={no_limit_entity:"pacing_no_limit",limit_unreadable:"pacing_limit_unreadable",write_refused:"pacing_write_refused",yielded:"pacing_yielded"}[e.action];if(i)return H`
                <div class="tonight-row" style="opacity:.85" title="${e.reason||""}">
                    <span>${this._t("charge_pacing")}</span>
                    <span>${this._t(i)}</span>
                </div>`;const r=Number(e.cap_w),a=Number.isFinite(r)&&r>0?`${(r/1e3).toFixed(1)} kW`:"",n=e.full_at?String(e.full_at).slice(11,16):"",o=e.enabled?"":`${this._t("pacing_would")} `,l=this._t(`pacing_${s}`),c=a?` · ${a}${n?` · ${this._t("pacing_full_by")} ${n}`:""}`:"";return H`
            <div class="tonight-row" style="opacity:.85" title="${e.reason||""}">
                <span>${this._t("charge_pacing")}</span>
                <span>${o}${l}${c}</span>
            </div>`}_renderSellLine(){const t=this._stateAttrs(`${this._prefix}battery_spendable_kwh`)||{},e=t.battery_sell_state;if("selling"!==e&&"scheduled"!==e)return K;const s=t.battery_sell_until?String(t.battery_sell_until).slice(11,16):"",i=Number(t.battery_sell_rate_w),r=Number.isFinite(i)&&i>0?` · ${(i/1e3).toFixed(1)} kW`:"",a="selling"===e?this._t("spend_selling"):this._t("spend_sell_planned");return H`
            <div class="tonight-row" style="opacity:.85">
                <span>${this._t("spend_sell")}</span>
                <span>${a}${s?` · ${this._t("spend_until")} ${s}`:""}${r}</span>
            </div>`}_renderLastNightLine(t){const e=Number(t.last_night_surplus_kwh);return Number.isFinite(e)?H`
            <div class="tonight-row" style="opacity:.85">
                <span>${this._t("last_night_surplus")}</span>
                <span>${this._fmt(e,1)} kWh</span>
            </div>`:K}_renderRateCaveat(t){return t.rate_caveat?H`<div class="tonight-why" style="opacity:.75">${this._t("rate_set_by_inverter")}</div>`:K}_fmt(t,e=1){return null==t||isNaN(t)?"—":t.toFixed(e)}_fmtDuration(t){if(null==t||isNaN(t))return"—";const e=Math.round(t);if(e<90)return`${e} min`;const s=Math.floor(e/60),i=e-60*s;return 0===i?`${s} h`:`${s} h ${i} min`}_batteryName(t){const e=this._hass?.states[`${this._prefix}battery_${t}_power`];let s=t.toUpperCase();return e?.attributes?.friendly_name&&(s=e.attributes.friendly_name.replace(/^SEM\s+/i,"").replace(/\s+Power$/i,"")),s}_renderMiniSocRing(t,e){const s=null!=t?Math.max(0,Math.min(100,t)):0,i=2*Math.PI*22,r=i*(1-s/100);return H`
            <svg viewBox="0 0 56 56" width="56" height="56"
                 style="display:block;">
                <circle cx="28" cy="28" r="${22}" fill="none"
                        stroke="rgba(255,255,255,0.12)" stroke-width="4" />
                <circle cx="28" cy="28" r="${22}" fill="none"
                        stroke="${e}" stroke-width="4"
                        stroke-linecap="round"
                        stroke-dasharray="${i.toFixed(1)}"
                        stroke-dashoffset="${r.toFixed(1)}"
                        transform="rotate(-90 28 28)" />
                <text x="28" y="32" text-anchor="middle"
                      fill="${e}" font-size="13" font-weight="800"
                      font-family="'Segoe UI','Roboto',sans-serif"
                      style="paint-order:stroke;stroke:rgba(0,0,0,0.45);stroke-width:0.5px;">
                    ${null!=t?Math.round(s)+"%":"—"}
                </text>
            </svg>
        `}_renderBatteryGlyph(t,e,s){const i=null!=t?Math.max(0,Math.min(100,t)):0,r=Math.max(2,i/100*52),a=s?"socPulse 2s ease-in-out infinite":"none";return H`
            <svg viewBox="0 0 44 76" width="40" height="69">
                <rect x="14" y="0" width="16" height="5" rx="2" fill="rgba(255,255,255,0.15)"/>
                <rect x="6" y="4" width="32" height="60" rx="4"
                    fill="none" stroke="rgba(255,255,255,0.15)" stroke-width="2"/>
                <rect x="9" y="${(52-r+7).toFixed(1)}" width="26"
                    height="${r.toFixed(1)}" rx="2"
                    fill="${e}" opacity="0.78" style="animation:${a}"/>
                <text x="22" y="40" text-anchor="middle"
                    fill="white" font-size="13" font-weight="700"
                    font-family="'Segoe UI','Roboto',sans-serif" opacity="0.95">
                    ${null!=t?Math.round(i)+"%":"—"}
                </text>
            </svg>
        `}_fmtHours(t){if(null==t||!isFinite(t)||t<=0)return"—";if(t<1)return`${Math.round(60*t)} min`;const e=Math.floor(t),s=Math.round(60*(t-e));return 0===s?`${e} h`:`${e} h ${s} min`}_batteryEta(t,e,s){if(null==t||e<=0||Math.abs(s)<50)return null;if(s>50){const i=(100-t)/100*e;return{key:"until_full",text:this._fmtHours(i/(s/1e3))}}const i=t/100*e;return{key:"until_empty",text:this._fmtHours(i/(Math.abs(s)/1e3))}}_renderModeControls(t,e){const s=this._hass?.states[t];if(!s)return K;const i=this._hass?.states[e],r=s.state,a=i&&("allow_arbitrage"===r||"force_discharge"===r),n=this._t("battery_mode_hint_"+r)||"";return H`
            <div class="battery-section-controls">
                <div class="bsc-row">
                    <span class="bsc-label">${this._t("mode")}</span>
                    <select class="bsc-select" .value=${r}
                            @click=${t=>t.stopPropagation()}
                            @change=${e=>this._selectOption(t,e.target.value)}>
                        ${(s.attributes.options||[]).map(t=>H`
                            <option value=${t} ?selected=${t===r}>
                                ${this._t("battery_mode_"+t)||t}
                            </option>`)}
                    </select>
                </div>
                ${n?H`
                    <div class="bsc-hint">
                        <ha-icon icon="mdi:information-outline"></ha-icon>
                        <span>${n}</span>
                    </div>
                `:K}
                ${a?H`
                    <div class="bsc-row">
                        <span class="bsc-label">${this._t("reserve_soc")}</span>
                        <span class="bsc-stepper">
                            <button class="bsc-btn"
                                @click=${()=>this._stepNumber(e,-1)}>−</button>
                            <span class="bsc-stepval">${Tt(At(i),0)}%</span>
                            <button class="bsc-btn"
                                @click=${()=>this._stepNumber(e,1)}>+</button>
                        </span>
                    </div>
                `:K}
            </div>
        `}_renderBatterySection(t,e){const s=be[e%be.length],i=this._val(`battery_${t}_power`,null),r=this._val(`battery_${t}_soc`,null),a=(this._valStr(`battery_${t}_status`)||"").toLowerCase(),n=this._val(`battery_${t}_capacity_kwh`,0),o=this._batteryName(t),l="selling"===a,c=!l&&("charging"===a||i>50),d=!l&&("discharging"===a||i<-50),p=c||d||l,_=l?"selling_to_grid":c?"charging":d?"discharging":"idle",h=null!=i||""!==a,u=l?"#FCD170":c?"#f06292":d?"#4db6ac":"#999",g=null!=r&&n>0?r/100*n:null,m=this._batteryEta(r,n,i);return H`
            <div class="battery-section">
                <div class="battery-section-header">
                    <div class="battery-dot" style="background:${s}"></div>
                    <span class="battery-section-name">${o}</span>
                    <span class="battery-section-status"
                          style="color:${u}">
                        ${h?this._t(_):Nt}
                    </span>
                </div>
                <div class="battery-section-body">
                    <div class="battery-section-glyph">
                        ${this._renderBatteryGlyph(r,u,p)}
                        <span class="battery-section-soc-label">SOC</span>
                    </div>
                    <div class="battery-section-metrics">
                        <div class="bs-row">
                            <span class="bs-label">${this._t("power")}</span>
                            <span class="bs-val"
                                  style="color:${i>50||i<-50?u:""}">
                                ${ut(i)}
                            </span>
                        </div>
                        ${null!=g?H`
                            <div class="bs-row">
                                <span class="bs-label">${this._t("stored")}</span>
                                <span class="bs-val">${this._fmt(g,1)} kWh</span>
                            </div>
                        `:K}
                        ${n>0?H`
                            <div class="bs-row">
                                <span class="bs-label">${this._t("capacity")}</span>
                                <span class="bs-val">${this._fmt(n,1)} kWh</span>
                            </div>
                        `:K}
                        ${m?H`
                            <div class="bs-row">
                                <span class="bs-label">${this._t(m.key)}</span>
                                <span class="bs-val">${m.text}</span>
                            </div>
                        `:K}
                    </div>
                </div>
                ${this._renderModeControls(`select.sem_battery_${t}_mode`,`number.sem_battery_${t}_reserve_soc`)}
            </div>
        `}_renderTonight(t){const e=`${this._prefix}battery_spendable_kwh`,s=this._hass?.states[e];if(!s)return K;const i=this._stateAttrs(e),r=i.phase;if(!r)return K;const a=t=>null==t||""===t||isNaN(parseFloat(t))?null:parseFloat(t),n=a(s.state),o=a(i.dynamic_floor_pct),l=a(i.nights_sealed)??0,c=a(i.nights_required)??5,d=a(i.forecast_days_d1)??0,p=a(i.forecast_days_required)??7,_={learning:t.warning||"#e0a943",holding:"#5bc8d8",spending:"#4db6ac"}[r]||t.textSec||"#888";let h,u;"learning"===r?(h=`${Math.min(l,c)}`,u=`${this._t("of")} ${c} ${this._t("nights")}`):(h=this._fmt(n??0,1),u=`kWh ${this._t("spendable_tonight")}`);const g=[];if("learning"===r)g.push([this._t("nights_recorded"),`${l}`]),g.push([this._t("forecast_days_settled"),`${d} / ${p}`]);else{const t=a(i.overnight_need_kwh),e=a(i.expected_refill_kwh);null!=t&&g.push([this._t("overnight_need"),`${this._fmt(t,1)} kWh`]),null!=e&&g.push([this._t("expected_refill"),`${this._fmt(e,1)} kWh`]),null!=o&&g.push([this._t("floor_tonight"),`${Math.round(o)}%`])}const m=[];for(let t=0;t<c;t++)m.push(t<l);return H`
            <div class="tonight" style="--tn-accent:${_}">
                <div class="tonight-head">
                    <span class="tonight-title">${this._t("tonight")}</span>
                    <span class="tonight-pill">${this._t(`planning_phase_${r}`)}</span>
                </div>
                <div class="tonight-big ${"spending"===r?"tn-live":"tn-dim"}">
                    ${h}<span class="tonight-unit">${u}</span>
                </div>
                ${"learning"===r?H`
                    <div class="tonight-prog">
                        ${m.map(t=>H`<i class="${t?"on":""}"></i>`)}
                    </div>
                    <button class="tonight-act" @click=${this._rebuildNights}
                            title=${this._t("rebuild_nights_hint")}>
                        ${this._t("rebuild_nights")}
                    </button>`:K}
                <div class="tonight-why">${i.why||""}</div>
                ${this._renderPacingLine()}
                ${this._renderSellLine()}
                ${this._renderLastNightLine(i)}
                ${this._renderRateCaveat(i)}
                ${g.length?H`
                    <div class="tonight-work">
                        ${g.map(([t,e])=>H`
                            <div class="tonight-row"><span>${t}</span><span>${e}</span></div>`)}
                    </div>`:K}
            </div>
        `}async _rebuildNights(t){const e=t?.currentTarget;e&&(e.disabled=!0,e.textContent=this._t("rebuild_nights_busy"));try{await this._hass.callService("solar_energy_management","backfill_battery_nights",{days:365})}catch(t){e&&(e.disabled=!1,e.textContent=this._t("rebuild_nights"))}}_renderEvidence(t){const e=`${this._prefix}battery_spendable_kwh`,s=this._stateAttrs(e);if(!s.phase)return K;const i=t=>null==t||""===t||isNaN(parseFloat(t))?null:parseFloat(t),r=t=>`${Math.round(100*t)}%`,a=i(s.forecast_days_required)??7,n=i(s.nights_required)??5,o=this._hass?.states[`${this._prefix}forecast_source`]?.state,l=t=>this._t(t),c=(t,e,n,c)=>{const d=i(s[t]),p=i(s[e])??0,_=s[n],h=me(o,c,l),u=function({available:t,trust:e,days:s,minDays:i,t:r}){return!1===t?r("horizon_not_published"):null==e?r("horizon_learning_effect").replace("{days}",String(s??0)).replace("{needed}",String(i??7)):r("horizon_trusted_effect")}({available:_,trust:d,days:p,minDays:a,t:l}),g=s[`forecast_d${c}_state`],m=s[`forecast_d${c}_path`];return"unsupported"===g||null==g&&!1===_?"disabled_by_integration"===m?{label:h,value:this._t("sensor_disabled"),sub:this._t("enable_horizon_sensor"),dim:!0}:{label:h,value:this._t("no_source"),sub:u,dim:!0}:"learning"===g&&null==d||null==d?{label:h,value:this._t("learning"),sub:u,dim:!0}:{label:h,value:r(d),sub:`${p} ${this._t("days_settled")} · ${u}`,dim:!1}},d=[c("forecast_trust_d1","forecast_days_d1","forecast_d1_available",1),c("forecast_trust_d2","forecast_days_d2","forecast_d2_available",2)],p=i(s.measured_capacity_kwh),_=i(s.capacity_samples)??0,h=i(s.capacity_drift_pct),u=i(s.nameplate_capacity_kwh);return null==p?d.push({label:this._t("measured_pack_size"),value:this._t("learning"),sub:`${_} / ${n} ${this._t("nights")} · `+fe({measuredKwh:null,nameplateKwh:u,t:l}),dim:!0}):d.push({label:this._t("measured_pack_size"),value:`${this._fmt(p,1)} kWh`,sub:(null==h?`${_} ${this._t("nights")}`:`${h>0?"+":""}${this._fmt(h,1)}% ${this._t("vs_nameplate")}`)+` · ${fe({measuredKwh:p,nameplateKwh:u,t:l})}`,dim:!1}),H`
            <div class="evidence">
                ${d.map(t=>H`
                    <div class="ev-cell">
                        <div class="ev-key">${t.label}</div>
                        <div class="ev-val ${t.dim?"ev-dim":""}">${t.value}</div>
                        <div class="ev-sub">${t.sub}</div>
                    </div>`)}
            </div>
        `}render(){if(!this._hass||!this._config)return K;const t=this._theme(),e=2*Math.PI*42,s=e.toFixed(1),i=this._val("battery_soc",null),r=It(i),a=this._val("battery_power",null),n=this._val("battery_charge_power",0),o=this._val("battery_discharge_power",0),l=(this._valStr("battery_status")||"").toLowerCase(),c=this._val("battery_health_score"),d=this._val("battery_cycles_estimated"),p=this._val("daily_battery_charge_energy"),_=this._val("daily_battery_discharge_energy"),h=this._val("daily_battery_savings"),u=this._val("monthly_battery_charge_energy"),g=this._val("monthly_battery_discharge_energy"),m=this._val("flow_solar_to_battery_energy",0),f=this._val("flow_grid_to_battery_energy",0),y=ft(this._hass),v=this._hass?.states[`${this._prefix}battery_temperature`],b=v&&"unavailable"!==v.state&&"unknown"!==v.state?parseFloat(v.state):null,x=($=v)&&$.attributes&&$.attributes.unit_of_measurement||"°C";var $;const w="selling"===l,k=!w&&("charging"===l||n>10),S=!w&&("discharging"===l||o>10),C=this._hass?.states["sensor.sem_tariff_current_export_rate"],z=C&&"unavailable"!==C.state&&"unknown"!==C.state?parseFloat(C.state):null,M="#FCD170",D=null!=a||""!==l,E=w?this._t("selling_to_grid"):k?this._t("charging"):S?this._t("discharging"):D?this._t("idle"):Nt,N=w?M:k?"#f06292":"#4db6ac",F=w?M:k?"#f06292":S?"#4db6ac":t.textSec||"#888",A=k||S||w?"0.5":"0.2",T=k||S||w?"socPulse 2s ease-in-out infinite":"none",I=r.fraction,R=(e*(1-I)).toFixed(1),B=p>0?Math.round(function(t,...e){const s=t=>{const e=Number(t);return Number.isFinite(e)&&e>0?e:0},i=s(t),r=e.reduce((t,e)=>t+s(e),i);return r>0?i/r*100:null}(m,f)??0):0,O=this._valStr("battery_session_type"),L="charge"===O||"discharge"===O,P="charge"===O,U=L?this._val("battery_session_energy"):0,W=L?this._val("battery_session_duration"):0,j=L?this._val("battery_session_avg_power"):0,G=L?this._val("battery_session_solar_share"):0,q=L?this._val("battery_session_cost"):0,V=L?this._val("battery_session_savings"):0,Y=P?"#f06292":"#4db6ac";t.dotColor;const Z=t.surface||"rgba(255,255,255,0.06)",X=t.surfaceBorder||"rgba(255,255,255,0.05)",J=t.surfaceHover||"rgba(255,255,255,0.12)",Q=t.textSec||"#999",tt=t.textTertiary||"#888";return H`
            <style>
                :host { display: block; contain: layout style paint; }
                .wrap {
                    padding: 16px 20px;
                    position: relative;
                    background: ${vt(t,pt.battery)};
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${t.text||"#e0e0e0"});
                }
                .glow-svg { position: absolute; width: 0; height: 0; }
                .hero { display: flex; align-items: center; gap: 20px; }
                @media (max-width: 400px) { .hero { flex-direction: column; gap: 12px; } }
                .battery-ring { position: relative; width: 100px; height: 100px; flex-shrink: 0; }
                .battery-ring svg { width: 100%; height: 100%; transform: rotate(-90deg); }
                .ring-bg { fill: none; stroke: rgba(77,182,172,0.12); stroke-width: 5; }
                .soc-arc {
                    fill: none; stroke-width: 5; stroke-linecap: round;
                    transition: stroke-dashoffset 1.5s cubic-bezier(0.4,0,0.2,1);
                    filter: url(#batt-glow);
                }
                .glow-ring {
                    fill: none; stroke-width: 8; opacity: 0.2;
                    filter: url(#batt-glow-soft);
                    animation: glowPulse 3s ease-in-out infinite;
                }
                @keyframes glowPulse { 0%,100% { opacity: 0.2; } 50% { opacity: 0.08; } }
                @keyframes socPulse  { 0%,100% { opacity: 1; }   50% { opacity: 0.6; } }
                .ring-center {
                    position: absolute; top: 50%; left: 50%;
                    transform: translate(-50%, -50%);
                    text-align: center; pointer-events: none;
                }
                .battery-icon { display: block; margin: 0 auto 1px; }
                .soc-value {
                    font-size: 14px; font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    text-shadow: 0 0 8px rgba(77,182,172,0.3); line-height: 1;
                }
                .metrics-col { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
                .metric-row {
                    display: flex; justify-content: space-between; align-items: baseline; padding: 2px 0; gap: 8px;
                }
                .metric-label { font-size: 12px; color: var(--secondary-text-color, ${Q}); font-weight: 500; }
                .metric-val { font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; color: #4db6ac; }
                .chips { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; }
                .chip {
                    flex: 1; min-width: 80px;
                    background: var(--secondary-background-color, ${Z});
                    border: 1px solid var(--divider-color, ${X});
                    border-radius: 10px; padding: 8px 10px; text-align: center;
                    transition: border-color 0.3s cubic-bezier(0.4,0,0.2,1);
                }
                .chip:hover { border-color: var(--divider-color, ${J}); }
                .chip-label {
                    font-size: 11px; color: var(--secondary-text-color, ${tt});
                    font-weight: 500; letter-spacing: 0.3px; margin-bottom: 3px;
                }
                .chip-value { font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }
                .c-charge { color: #f06292; }
                .c-discharge { color: #4db6ac; }
                .c-savings { color: #8DC892; }
                .chip-src { font-size: 10px; color: var(--secondary-text-color, ${tt}); margin-top: 1px; }
                .session-section {
                    margin-top: 14px; padding: 10px 12px;
                    background: var(--secondary-background-color, ${Z});
                    border: 1px solid var(--divider-color, ${X});
                    border-radius: 10px;
                }
                .sess-header { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
                .sess-title {
                    font-size: 12px; font-weight: 600;
                    text-transform: uppercase; letter-spacing: 0.5px;
                }
                .sess-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4px; }
                .sess-item-label { font-size: 11px; color: var(--secondary-text-color, ${tt}); }
                .sess-item-value {
                    font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${t.text||"#e0e0e0"});
                }
                .monthly-section { display: flex; gap: 8px; margin-top: 10px; }

                /* ── Per-battery sections (Phase B). Same structural
                       shape as the EV card's per-charger sections so
                       a user who already knows the EV tab reads the
                       battery tab without re-learning the layout. ── */
                /* (#778) Tonight — the forecast budget panel. Accent is set
                   per phase from JS so the three states read at a glance
                   without three copies of this block. */
                .tonight {
                    background: rgba(255,255,255,.03);
                    border: 1px solid rgba(255,255,255,.08);
                    border-left: 3px solid var(--tn-accent, #4db6ac);
                    border-radius: 12px;
                    padding: 14px 16px 15px;
                    margin: 4px 0 14px;
                    display: flex;
                    flex-direction: column;
                    gap: 10px;
                }
                .tonight-head {
                    display: flex;
                    align-items: baseline;
                    justify-content: space-between;
                    gap: 12px;
                }
                .tonight-title {
                    font-size: 14px;
                    font-weight: 500;
                    color: var(--sem-text, #e8eeed);
                }
                .tonight-pill {
                    font-size: 10px;
                    letter-spacing: .08em;
                    text-transform: uppercase;
                    padding: 3px 8px;
                    border-radius: 20px;
                    border: 1px solid var(--tn-accent, #4db6ac);
                    color: var(--tn-accent, #4db6ac);
                    white-space: nowrap;
                }
                .tonight-big {
                    font-size: 32px;
                    font-weight: 300;
                    line-height: 1;
                    font-variant-numeric: tabular-nums;
                    display: flex;
                    align-items: baseline;
                    gap: 6px;
                    flex-wrap: wrap;
                }
                .tonight-big.tn-live { color: var(--tn-accent, #4db6ac); }
                .tonight-big.tn-dim { color: var(--sem-text-sec, #9bb0ab); }
                .tonight-unit {
                    font-size: 13px;
                    font-weight: 400;
                    color: var(--sem-text-sec, #9bb0ab);
                }
                .tonight-prog { display: flex; gap: 4px; }
                .tonight-prog i {
                    flex: 1;
                    height: 5px;
                    border-radius: 3px;
                    background: rgba(255,255,255,.13);
                }
                .tonight-prog i.on { background: var(--tn-accent, #e0a943); }
                /* (#877) A quiet offer, not a call to action — the wait is
                   normal and the shortcut is optional. Sits under the pips
                   it removes. */
                .tonight-act {
                    /* .tonight is a column flex with align-items:stretch and
                       its own 10px gap — so a bare button stretched to the
                       full 822px card width and carried double spacing. The
                       layout owns the gap; this only opts out of the
                       stretch. */
                    align-self: flex-start;
                    padding: 5px 11px;
                    font: inherit;
                    font-size: 0.78em;
                    letter-spacing: 0.02em;
                    color: var(--tn-accent, #e0a943);
                    background: transparent;
                    border: 1px solid var(--tn-accent, #e0a943);
                    border-radius: 999px;
                    cursor: pointer;
                    opacity: 0.85;
                    transition: opacity 0.15s, background 0.15s;
                }
                .tonight-act:hover { opacity: 1; background: rgba(255,255,255,0.06); }
                .tonight-act:disabled { opacity: 0.5; cursor: default; }
                .tonight-why {
                    font-size: 12.5px;
                    line-height: 1.45;
                    color: var(--sem-text-sec, #9bb0ab);
                }
                .tonight-work {
                    display: flex;
                    flex-direction: column;
                    gap: 4px;
                    border-top: 1px solid rgba(255,255,255,.08);
                    padding-top: 9px;
                }
                .tonight-row {
                    display: flex;
                    justify-content: space-between;
                    gap: 16px;
                    font-size: 11.5px;
                    color: var(--sem-text-sec, #8fa3a0);
                }
                .tonight-row span:last-child {
                    font-variant-numeric: tabular-nums;
                    color: var(--sem-text, #cfdad7);
                }

                /* (#778) the evidence strip */
                .evidence {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                    gap: 8px;
                    margin: 0 0 14px;
                }
                .ev-cell {
                    background: rgba(255,255,255,.03);
                    border: 1px solid rgba(255,255,255,.07);
                    border-radius: 10px;
                    padding: 10px 12px;
                    display: flex;
                    flex-direction: column;
                    gap: 3px;
                }
                .ev-key {
                    font-size: 10px;
                    letter-spacing: .07em;
                    text-transform: uppercase;
                    color: var(--sem-text-sec, #8fa3a0);
                }
                .ev-val {
                    font-size: 19px;
                    font-weight: 300;
                    font-variant-numeric: tabular-nums;
                    color: var(--sem-text, #e8eeed);
                }
                .ev-val.ev-dim { font-size: 15px; color: var(--sem-text-sec, #9bb0ab); }
                .ev-sub {
                    font-size: 11px;
                    line-height: 1.35;
                    color: var(--sem-text-sec, #8fa3a0);
                }

                .battery-sections {
                    margin-top: 16px;
                    display: flex; flex-direction: column;
                    gap: 12px;
                }
                .battery-section {
                    background: ${Z};
                    border: 1px solid ${X};
                    border-radius: 12px;
                    padding: 12px 14px;
                }
                .battery-section-header {
                    display: flex; align-items: center; gap: 8px;
                    margin-bottom: 10px;
                }
                .battery-dot {
                    width: 8px; height: 8px;
                    border-radius: 50%;
                    flex-shrink: 0;
                }
                .battery-section-name {
                    flex: 1; font-weight: 600; font-size: 0.95em;
                    color: var(--primary-text-color, ${t.text||"#e0e0e0"});
                }
                .battery-section-status {
                    font-size: 0.8em; font-weight: 500;
                    text-transform: uppercase; letter-spacing: 0.05em;
                }
                .battery-section-body {
                    display: flex; align-items: center; gap: 12px;
                }
                .battery-section-ring {
                    flex-shrink: 0; width: 56px; text-align: center;
                }
                .battery-section-glyph {
                    flex-shrink: 0; width: 44px; text-align: center;
                }
                .battery-section-soc-label {
                    display: block;
                    font-size: 10px; color: ${Q};
                    margin-top: 2px;
                    text-transform: uppercase; letter-spacing: 0.05em;
                }
                .battery-section-metrics {
                    flex: 1;
                    display: flex; flex-direction: column; gap: 2px;
                }
                .bs-row {
                    display: flex; justify-content: space-between; align-items: baseline;
                    padding: 2px 0;
                }
                .bs-label {
                    font-size: 11px; color: ${Q};
                    font-weight: 500;
                }
                .bs-val {
                    font-size: 12px; font-weight: 600;
                    color: var(--primary-text-color, ${t.text||"#e0e0e0"});
                    font-variant-numeric: tabular-nums;
                }
                /* Per-battery controls (#523) — mode select + reserve stepper */
                .battery-section-controls {
                    margin-top: 10px; padding-top: 10px;
                    border-top: 1px solid ${X};
                    display: flex; flex-direction: column; gap: 8px;
                }
                .bsc-row {
                    display: flex; align-items: center; justify-content: space-between;
                    gap: 8px;
                }
                .bsc-hint {
                    display: flex; align-items: flex-start; gap: 5px;
                    font-size: 11px; line-height: 1.35;
                    color: ${Q};
                    margin: -2px 0 1px 0;
                    opacity: 0.92;
                }
                .bsc-hint ha-icon {
                    --mdc-icon-size: 13px;
                    flex: 0 0 auto; margin-top: 1px; opacity: 0.8;
                }
                .bsc-label {
                    font-size: 12px; color: ${Q}; font-weight: 500;
                }
                .bsc-select {
                    background: ${Z};
                    color: var(--primary-text-color, ${t.text||"#e0e0e0"});
                    border: 1px solid ${X};
                    border-radius: 8px; padding: 5px 8px; font-size: 12px;
                    font-weight: 600; cursor: pointer; min-width: 150px;
                }
                .bsc-stepper { display: flex; align-items: center; gap: 8px; }
                .bsc-btn {
                    width: 24px; height: 24px; border-radius: 6px;
                    background: ${Z}; border: 1px solid ${X};
                    color: var(--primary-text-color, ${t.text||"#e0e0e0"});
                    font-size: 15px; font-weight: 700; cursor: pointer; line-height: 1;
                }
                .bsc-btn:hover { border-color: ${J}; }
                .bsc-stepval {
                    min-width: 38px; text-align: center; font-size: 13px;
                    font-weight: 700; font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${t.text||"#e0e0e0"});
                }
                /* Phase B mobile breakpoint — single column from the
                   ring + metrics layout collapses to stacked at
                   < 480 px (mirrors the sem-solar-card pattern). */
                @media (max-width: 480px) {
                    .battery-section-body {
                        flex-direction: column;
                        align-items: stretch;
                    }
                    .battery-section-ring { margin: 0 auto; }
                    .battery-section-glyph { margin: 0 auto; }
                }
                .month-chip {
                    flex: 1; text-align: center; padding: 6px 8px;
                    background: var(--secondary-background-color, ${Z});
                    border: 1px solid var(--divider-color, ${X});
                    border-radius: 8px;
                }
            </style>

            <svg class="glow-svg">
                <defs>
                    <filter id="batt-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="4" result="blur"/>
                        <feFlood flood-color="${N}" flood-opacity="0.25" result="color"/>
                        <feComposite in="color" in2="blur" operator="in" result="glow"/>
                        <feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                    <filter id="batt-glow-soft" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="6" result="blur"/>
                        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                </defs>
            </svg>

            <ha-card>
                <div class="wrap">
                    <div class="hero">
                        <div class="battery-ring">
                            <svg viewBox="0 0 100 100">
                                <circle class="glow-ring" cx="50" cy="50" r="42"
                                    style="stroke:${N};opacity:${A}"/>
                                <circle class="ring-bg" cx="50" cy="50" r="42"/>
                                <circle class="soc-arc" cx="50" cy="50" r="42"
                                    stroke-dasharray="${s}"
                                    style="stroke-dashoffset:${R};stroke:${N};animation:${T}"/>
                            </svg>
                            <div class="ring-center">
                                <!-- #523/#524 follow-up: filled SOC-level
                                     battery glyph matching the system card
                                     (was a flat outline). Fills bottom-up to
                                     SOC, tints with the arc colour, and shows a
                                     charging bolt. -->
                                <svg class="battery-icon" width="18" height="26" viewBox="0 0 20 30">
                                    <rect x="6" y="0" width="8" height="4" rx="1.5"
                                        fill="${N}" opacity="0.7"/>
                                    <rect x="2" y="4" width="16" height="26" rx="3"
                                        fill="rgba(0,0,0,0.30)" stroke="${N}"
                                        stroke-width="1.6" opacity="0.9"/>
                                    <rect x="4" y="${(28-22*I).toFixed(1)}" width="12"
                                        height="${(22*I).toFixed(1)}" rx="1.5"
                                        fill="${N}" opacity="0.55"/>
                                    <path d="M11,9.5 L6.5,18.5 L9.5,18.5 L8.5,24.5 L13.5,15 L10.5,15 Z"
                                        fill="#FCD170" opacity="${k?.95:0}"/>
                                </svg>
                                <div class="soc-value" style="color:${N}">
                                    ${r.label}
                                </div>
                            </div>
                        </div>

                        <div class="metrics-col">
                            <div class="metric-row">
                                <span class="metric-label">${this._t("soc")}</span>
                                <span class="metric-val">${this._fmt(i,1)}%</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("power")}</span>
                                <span class="metric-val">${ut(a)}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("status")}</span>
                                <span class="metric-val" style="color:${F}">${E}</span>
                            </div>
                            ${w&&null!=z?H`
                            <div class="metric-row">
                                <span class="metric-label">${this._t("export_rate")}</span>
                                <span class="metric-val" style="color:${M}">${this._fmt(z,3)} ${y}/kWh</span>
                            </div>
                            `:K}
                            <div class="metric-row">
                                <span class="metric-label">${this._t("health")}</span>
                                <span class="metric-val">${this._fmt(c,1)}%</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("cycles")}</span>
                                <span class="metric-val">${this._fmt(d,1)}</span>
                            </div>
                            ${this._batteries.length>1?"":H`
                                <div class="metric-row">
                                    <span class="metric-label">${this._t("temperature")}</span>
                                    <span class="metric-val">
                                        ${null!=b?`${this._fmt(b,1)} ${x}`:"—"}
                                    </span>
                                </div>
                            `}
                            <!-- #404: On multi-battery installs (length > 1)
                                 the fleet-tile temperature is hidden because
                                 each battery has its own temperature shown in
                                 its per-battery section. Per RienduPre's UX
                                 confirmation 2026-06-04. Single-battery
                                 installs (today's PROD majority) unchanged. -->
                        </div>
                    </div>

                    ${this._batteries.length>=1?H`
                        <div class="battery-sections">
                            ${this._batteries.map((t,e)=>this._renderBatterySection(t,e))}
                        </div>
                    `:H`
                        <!-- Single-battery install (#523): global mode control
                             on the hero, no per-battery section. -->
                        ${this._renderModeControls("select.sem_battery_mode","number.sem_battery_reserve_soc")}
                    `}

                    <div class="session-section">
                        <div class="sess-header">
                            <ha-icon icon="mdi:battery-sync"
                                style="--mdc-icon-size:14px;color:${L?Y:t.textSec}">
                            </ha-icon>
                            <span class="sess-title" style="color:${L?Y:t.textSec}">
                                ${this._t("current_session")}
                            </span>
                        </div>
                        ${L?H`
                        <div class="sess-grid">
                            <div>
                                <div class="sess-item-label">${this._t("energy")}</div>
                                <div class="sess-item-value">${this._fmt(U,2)} kWh</div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t("duration")}</div>
                                <div class="sess-item-value">${this._fmtDuration(W)}</div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t("avg_power")}</div>
                                <div class="sess-item-value">${ut(j)}</div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t("source")}</div>
                                <div class="sess-item-value">
                                    ${P?`${this._t("solar")}: ${this._fmt(G,0)}%`:""}
                                </div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t("cost")}</div>
                                <div class="sess-item-value">
                                    ${P?`${this._fmt(q,2)} ${y}`:`${this._t("saved")} ${this._fmt(V,2)} ${y}`}
                                </div>
                            </div>
                        </div>
                        `:H``}
                    </div>

                    ${this._renderTonight(t)}
                    ${this._renderEvidence(t)}

                    <div class="chips">
                        <div class="chip">
                            <div class="chip-label">${this._t("charge_today")}</div>
                            <div class="chip-value c-charge">${this._fmt(p,2)} kWh</div>
                            <div class="chip-src">
                                ${B>0?`${B}% ${this._t("solar")}`:""}
                            </div>
                        </div>
                        <div class="chip">
                            <div class="chip-label">${this._t("discharge_today")}</div>
                            <div class="chip-value c-discharge">${this._fmt(_,2)} kWh</div>
                        </div>
                        <div class="chip">
                            <div class="chip-label">${this._t("savings_today")}</div>
                            <div class="chip-value c-savings">
                                ${this._fmt(h,2)} ${y}
                            </div>
                        </div>
                    </div>

                    <div class="monthly-section">
                        <div class="month-chip">
                            <div class="chip-label">
                                ${this._t("monthly")} ${this._t("charge")}
                            </div>
                            <div class="chip-value c-charge">${this._fmt(u,1)} kWh</div>
                        </div>
                        <div class="month-chip">
                            <div class="chip-label">
                                ${this._t("monthly")} ${this._t("discharge")}
                            </div>
                            <div class="chip-value c-discharge">${this._fmt(g,1)} kWh</div>
                        </div>
                    </div>
                </div>
            </ha-card>
        `}getCardSize(){return 3}static getStubConfig(){return{}}},{type:"sem-battery-card",name:"SEM Battery",description:"Lumina-styled battery hero card with SOC arc ring and key metrics",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-battery-card"});const xe="flat",$e="no_prices",we={negative:"price_negative",[xe]:"price_level_flat",[$e]:"price_level_no_prices"};function ke(t){const e=String(t||"").toLowerCase();return we[e]||e}function Se(t,e="#888"){switch(String(t||"").toLowerCase()){case"negative":return"#4db6ac";case"very_cheap":case"cheap":return"#8DC892";case"normal":return"#ff9800";case"expensive":return"#f06292";case"very_expensive":return"#e53935";case xe:case $e:return"#9e9e9e";default:return e}}const Ce="sensor.sem_",ze=["grid_power","grid_import_power","grid_export_power","grid_status","daily_grid_import_energy","daily_grid_export_energy","monthly_grid_import_energy","monthly_grid_export_energy","consecutive_peak_15min","monthly_consecutive_peak","current_vs_peak_percentage","target_peak_limit","peak_margin","peak_trend","export_guard_state","load_management_status","loads_currently_shed","available_load_reduction","controllable_devices_count","tariff_current_import_rate","tariff_current_export_rate","tariff_price_level","tariff_today_min_price","tariff_today_max_price","surplus_total_w","surplus_unallocated_w","surplus_active_devices","surplus_total_devices"];kt("sem-grid-card",class extends Lt{static get watchedEntities(){return ze.map(t=>`${Ce}${t}`)}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||Ce}set hass(t){this._hass=t;const e=t?.language,s="function"==typeof semLocalize;let i=!1;if((e!==this._lang||s&&!this._localizeReady)&&(this._lang=e,this._localizeReady=s,i=!0),this._isFrozen()&&!i)return;const r=ze.map(e=>t?.states[`${this._prefix}${e}`]?.state||"").join(",")+"|"+e;(r!==this._lastGridKey||i)&&(this._lastGridKey=r,this._scheduleUpdate())}get hass(){return this._hass}_val(t,e=null){return this._state(`${this._prefix}${t}`,e)}_valStr(t){return this._stateStr(`${this._prefix}${t}`)}_fmt(t,e=1){return null==t||isNaN(t)?"—":t.toFixed(e)}_peakColor(t){return t>=90?"#f06292":t>=70?"#ff9800":"#8DC892"}_priceLevelColor(t){return"high"===t?"#f06292":"low"===t?"#8DC892":Se(t,"#888")}_metricRow(t,e){return H`
            <div class="metric-row">
                <span class="metric-label">${this._t(t)}</span>
                <span class="metric-val">${e}</span>
            </div>
        `}render(){if(!this._hass||!this._config)return K;const t=this._theme(),e=ft(this._hass),s=this._val("grid_import_power"),i=this._val("grid_export_power"),r=i>s&&i>10,a=s>10,n=r?"mdi:transmission-tower-export":"mdi:transmission-tower-import",o=r?"#8353d1":"#488fc2",l=a||r?"0.45":"0.1",c=this._valStr("grid_status"),d=["grid_power","grid_import_power","grid_export_power"].some(t=>!Ft(this._hass?.states[`${this._prefix}${t}`])),p=""!==c&&"—"!==c?this._t(c.toLowerCase()):d?r?this._t("exporting"):a?this._t("importing"):this._t("idle"):Nt,_=r?"#8353d1":a?"#488fc2":"#888",h=this._val("daily_grid_import_energy"),u=this._val("daily_grid_export_energy"),g=null==h||null==u?null:h-u,m=null==g?"var(--secondary-text-color, #888)":g<=0?"#8353d1":"#488fc2",f=this._val("current_vs_peak_percentage"),y=this._val("export_guard_state"),v=this._val("consecutive_peak_15min"),b=this._val("monthly_consecutive_peak"),x=this._val("target_peak_limit"),$=this._val("peak_margin"),w=this._valStr("peak_trend"),k=this._peakColor(f),S=$>0?"#8DC892":"#f06292",C=(200*Math.min(Math.max(f/100,0),1)).toFixed(1),z=this._val("loads_currently_shed"),M=this._val("available_load_reduction"),D=this._val("controllable_devices_count"),E=this._val("tariff_current_import_rate"),N=this._val("tariff_current_export_rate"),F=this._valStr("tariff_price_level"),A=this._val("tariff_today_min_price"),T=this._val("tariff_today_max_price"),I=this._priceLevelColor(F),R=this._val("surplus_total_w"),B=this._val("surplus_unallocated_w"),O=null==R||null==B?null:Math.max(0,R-B),L=this._val("surplus_active_devices"),P=this._val("surplus_total_devices");t.dotColor;const U=t.textSec||"#999",W=t.surface||"rgba(255,255,255,0.06)",j=t.surfaceBorder||"rgba(255,255,255,0.12)";return H`
            <style>
                :host { display: block; }
                .wrap {
                    padding: 16px 20px;
                    position: relative;
                    background: ${vt(t,pt.inverter)};
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${t.text||"#e0e0e0"});
                }
                .glow-svg { position: absolute; width: 0; height: 0; }
                .hero { display: flex; align-items: center; gap: 16px; padding-bottom: 8px; }
                @media (max-width: 400px) { .hero { flex-direction: column; gap: 10px; } }
                .grid-icon-area { position: relative; width: 80px; height: 80px; flex-shrink: 0; }
                .grid-icon-area svg { width: 100%; height: 100%; }
                .grid-glow-ring {
                    fill: none; stroke-width: 6;
                    filter: url(#grid-glow-soft);
                    transition: stroke 0.4s ease, opacity 0.4s ease;
                }
                .ring-bg { fill: none; stroke: rgba(72,143,194,0.12); stroke-width: 3; }
                .ring-fill { fill: rgba(72,143,194,0.06); }
                .hero-info { flex: 1; min-width: 0; }
                .hero-power-row { display: flex; gap: 14px; margin-bottom: 4px; flex-wrap: wrap; }
                .hero-pw { display: flex; flex-direction: column; }
                .hero-pw-label {
                    font-size: 12px; text-transform: uppercase; letter-spacing: 0.4px;
                    color: var(--secondary-text-color, ${U}); margin-bottom: 1px;
                }
                .hero-pw-val { font-size: 17px; font-weight: 700; font-variant-numeric: tabular-nums; }
                .hero-pw-val.import { color: #488fc2; }
                .hero-pw-val.export { color: #8353d1; }
                .hero-status {
                    font-size: 12px; font-weight: 500;
                    text-transform: uppercase; letter-spacing: 0.5px;
                }
                .section {
                    margin-top: 10px; padding: 10px 12px;
                    background: var(--secondary-background-color, ${W});
                    border: 1px solid var(--divider-color, ${j});
                    border-radius: 10px;
                }
                .section-title {
                    font-size: 12px; font-weight: 600; text-transform: uppercase;
                    letter-spacing: 0.6px; margin-bottom: 6px;
                }
                .metric-row {
                    display: flex; justify-content: space-between; align-items: baseline; padding: 2px 0;
                }
                .metric-label {
                    font-size: 12px; color: var(--secondary-text-color, ${U}); font-weight: 500;
                }
                .metric-val {
                    font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${t.text||"#e0e0e0"});
                }
                .net-row {
                    margin-top: 4px; padding-top: 4px;
                    border-top: 1px solid var(--divider-color, ${j});
                }
                .peak-bar-wrap { margin: 6px 0 4px; position: relative; }
                .peak-bar-bg { width: 100%; height: 8px; fill: rgba(72,143,194,0.12); }
                .peak-bar-fill {
                    height: 8px;
                    transition: width 0.8s cubic-bezier(0.4,0,0.2,1), fill 0.4s ease;
                }
                .peak-bar-svg { width: 100%; height: 8px; display: block; }
                .peak-pct-label {
                    font-size: 12px; font-weight: 700; font-variant-numeric: tabular-nums;
                    margin-top: 2px; text-align: right;
                }
                .c-import { color: #488fc2; }
                .c-export { color: #8353d1; }
                .c-green  { color: #8DC892; }
                .c-solar  { color: #ff9800; }
            </style>

            <svg class="glow-svg">
                <defs>
                    <filter id="grid-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="4" result="blur"/>
                        <feFlood flood-color="#488fc2" flood-opacity="0.3" result="color"/>
                        <feComposite in="color" in2="blur" operator="in" result="glow"/>
                        <feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                    <filter id="grid-glow-soft" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="6" result="blur"/>
                        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                </defs>
            </svg>

            <ha-card>
                <div class="wrap">
                    <!-- Hero -->
                    <div class="hero">
                        <div class="grid-icon-area">
                            <svg viewBox="0 0 80 80">
                                <circle class="grid-glow-ring" cx="40" cy="40" r="34"
                                    style="stroke:${o};opacity:${l}"/>
                                <circle class="ring-bg" cx="40" cy="40" r="34"/>
                                <circle class="ring-fill" cx="40" cy="40" r="31"/>
                                <foreignObject x="14" y="14" width="52" height="52">
                                    <div xmlns="http://www.w3.org/1999/xhtml"
                                        style="width:52px;height:52px;display:flex;align-items:center;justify-content:center">
                                        <ha-icon icon="${n}"
                                            style="--mdc-icon-size:28px;color:${o}">
                                        </ha-icon>
                                    </div>
                                </foreignObject>
                            </svg>
                        </div>

                        <div class="hero-info">
                            <div class="hero-power-row">
                                <div class="hero-pw">
                                    <span class="hero-pw-label">${this._t("import")}</span>
                                    <span class="hero-pw-val import">
                                        ${a?ut(s):"—"}
                                    </span>
                                </div>
                                <div class="hero-pw">
                                    <span class="hero-pw-label">${this._t("export")}</span>
                                    <span class="hero-pw-val export">
                                        ${r?ut(i):"—"}
                                    </span>
                                </div>
                            </div>
                            <div class="hero-status" style="color:${_}">${p}</div>
                        </div>
                    </div>

                    <!-- Today -->
                    <div class="section">
                        <div class="section-title" style="color:#488fc2">${this._t("today")}</div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("import")}</span>
                            <span class="metric-val c-import">${this._fmt(h,2)} kWh</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("export")}</span>
                            <span class="metric-val c-export">${this._fmt(u,2)} kWh</span>
                        </div>
                        <div class="metric-row net-row">
                            <span class="metric-label"><strong>${this._t(g<=0?"net_export":"net_import")}</strong></span>
                            <span class="metric-val" style="color:${m}">
                                ${this._fmt(null==g?null:Math.abs(g),2)} kWh
                            </span>
                        </div>
                    </div>

                    <!-- Peak Management -->
                    <div class="section">
                        <div class="section-title" style="color:#488fc2">${this._t("peak_management")}</div>
                        <div class="peak-bar-wrap">
                            <svg class="peak-bar-svg" viewBox="0 0 200 8" preserveAspectRatio="none">
                                <rect class="peak-bar-bg" x="0" y="0" width="200" height="8" rx="4" ry="4"/>
                                <rect class="peak-bar-fill" x="0" y="0"
                                    width="${C}" height="8" rx="4" ry="4"
                                    fill="${k}"/>
                            </svg>
                        </div>
                        <div class="peak-pct-label" style="color:${k}">
                            ${this._fmt(f,0)}%
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("peak_15min")}</span>
                            <span class="metric-val">${ut(v)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("monthly_peak")}</span>
                            <span class="metric-val">${ut(b)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("peak_limit")}</span>
                            <span class="metric-val">${ut(x)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("peak_margin")}</span>
                            <span class="metric-val" style="color:${S}">
                                ${ut($)}
                            </span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("trend")}</span>
                            <span class="metric-val">${w?this._t(w):"—"}</span>
                            ${y&&"unknown"!==y&&"unavailable"!==y?H`
                                <div class="row" style="opacity:.85"><span>${this._t("export_guard")}</span><span>${y}</span></div>`:K}
                        </div>
                    </div>

                    <!-- Load Control -->
                    <div class="section">
                        <div class="section-title" style="color:#488fc2">${this._t("load_control")}</div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("status")}</span>
                            <span class="metric-val">${this._valLabel("load_management_status")||"—"}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("loads_shed")}</span>
                            <span class="metric-val">${this._fmt(z,0)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("available_reduction")}</span>
                            <span class="metric-val">${ut(M)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("controllable_devices")}</span>
                            <span class="metric-val">${this._fmt(D,0)}</span>
                        </div>
                    </div>

                    <!-- Tariff -->
                    <div class="section">
                        <div class="section-title" style="color:#488fc2">${this._t("tariff")}</div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("import_rate")}</span>
                            <span class="metric-val c-import">
                                ${null!=E?`${this._fmt(E,4)} ${e}/kWh`:"—"}
                            </span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("export_rate")}</span>
                            <span class="metric-val c-export">
                                ${null!=N?`${this._fmt(N,4)} ${e}/kWh`:"—"}
                            </span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("price_level")}</span>
                            <span class="metric-val" style="color:${I}">
                                ${F?this._t(ke(F)):"—"}
                            </span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("today_min")}</span>
                            <span class="metric-val c-green">
                                ${null!=A?this._fmt(A,4):"—"}
                            </span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("today_max")}</span>
                            <span class="metric-val c-solar">
                                ${null!=T?this._fmt(T,4):"—"}
                            </span>
                        </div>
                    </div>

                    <!-- Surplus -->
                    <div class="section">
                        <div class="section-title" style="color:#488fc2">${this._t("surplus")}</div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("total_surplus")}</span>
                            <span class="metric-val c-solar">${ut(R)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("allocated")}</span>
                            <span class="metric-val">${ut(O)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("unallocated")}</span>
                            <span class="metric-val c-green">${ut(B)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("active_devices")}</span>
                            <span class="metric-val">
                                ${Tt(L,0)} / ${Tt(P,0)}
                            </span>
                        </div>
                    </div>
                </div>
            </ha-card>
        `}getCardSize(){return 5}static getStubConfig(){return{entity_prefix:Ce}}},{type:"sem-grid-card",name:"SEM Grid",description:"Consolidated grid card with import/export, peak management, load control, tariff, and surplus",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-grid-card"});const Me="sensor.sem_",De=20;function Ee(t){return 36+556*t}function Ne(t){if(!t||"string"!=typeof t)return null;const e=t.match(/^(\d{1,2}):(\d{2})$/);if(!e)return null;const s=parseInt(e[1],10),i=parseInt(e[2],10);return s>24||i>59?null:(s+i/60)/24}function Fe(t){if(!Array.isArray(t))return[];const e=[];let s=-1;for(let i=0;i<24;i++)t[i]&&-1===s?s=i:t[i]||-1===s||(e.push({start:s/24,end:i/24}),s=-1);return-1!==s&&e.push({start:s/24,end:1}),e}kt("sem-schedule-card",class extends Lt{static get watchedEntities(){return[`${Me}tariff_current_import_rate`,`${Me}tariff_price_level`,`${Me}night_start_time`,`${Me}night_end_time`,`${Me}best_surplus_window`,`${Me}predicted_surplus_window`,`${Me}ev_power`,`${Me}charging_state`,`${Me}surplus_total_w`]}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||Me}set hass(t){this._hass=t;const e=t?.language,s="function"==typeof semLocalize;let i=!1;if((e!==this._lang||s&&!this._localizeReady)&&(this._lang=e,this._localizeReady=s,i=!0),this._isFrozen()&&!i)return;const r=["tariff_current_import_rate","tariff_price_level","night_start_time","night_end_time","best_surplus_window","predicted_surplus_window","ev_power","charging_state"].map(e=>{const s=t?.states[`${this._prefix}${e}`];return(s?.state||"")+JSON.stringify(s?.attributes?.schedule_today||"")+JSON.stringify(s?.attributes?.tariff_schedule_today||"")+JSON.stringify(s?.attributes?.schedule_surplus_hours||"")+JSON.stringify(s?.attributes?.schedule_ev_hours||"")}),a=r.join("|")+"|"+e;(a!==this._lastSchedKey||i)&&(this._lastSchedKey=a,this._scheduleUpdate())}get hass(){return this._hass}_stateObj(t){return this._hass?.states[`${this._prefix}${t}`]||null}_getTariffSchedule(){const t=this._stateObj("tariff_current_import_rate")||this._stateObj("tariff_price_level"),e=t?.attributes?.schedule_today||t?.attributes?.tariff_schedule_today;if(Array.isArray(e)&&e.length>0)return e.map(t=>({start:Ne(t.start)??0,end:Ne(t.end)??1,level:t.level||(null===t.tariff?"no_prices":"NT"===(t.tariff||t.type||"HT").toUpperCase()?"cheap":"normal"),type:null===t.tariff?"":(t.tariff||t.type||"HT").toUpperCase(),avgPrice:t.avg_price}));const s=this._stateObj("tariff_price_level")?.state,i=new Set(["cheap","very_cheap","normal","expensive","very_expensive"]);return s&&i.has(s)?[{start:0,end:1,level:s,type:"cheap"===s||"very_cheap"===s?"NT":"HT",isFallback:!0}]:[{start:0,end:1,level:$e,type:"",isFallback:!0}]}_getNightWindow(){const t=Ne(this._stateObj("night_start_time")?.state),e=Ne(this._stateObj("night_end_time")?.state);return null==t||null==e?null:{start:t,end:e}}_getPredictedSurplusWindow(){for(const t of["predicted_surplus_window","best_surplus_window"]){const e=this._stateObj(t)?.state;if(!e||"unknown"===e||"unavailable"===e)continue;if(e.toLowerCase().startsWith("tomorrow"))continue;const s=e.split(/[-–]/);if(2!==s.length)continue;const i=Ne(s[0].trim()),r=Ne(s[1].trim());if(null!=i&&null!=r)return{start:i,end:r}}return null}_getSurplusBlocks(){const t=this._hass?.states[`${this._prefix}surplus_total_w`];return Fe(t?.attributes?.schedule_surplus_hours)}_getEvBlocks(){const t=this._hass?.states[`${this._prefix}surplus_total_w`];return Fe(t?.attributes?.schedule_ev_hours)}_getEvPlanWindow(){const t=this._stateObj("charging_state"),e=t?.attributes?.today_plan;if(!Array.isArray(e))return null;const s=new Date;s.setHours(0,0,0,0);const i=s.getTime()+864e5,r=t=>{const e=new Date(t).getTime();return e<s.getTime()||e>=i?null:(e-s.getTime())/864e5};let a,n,o,l;for(const t of e)"ev_charge_start"===t.kind?a=r(t.when):"ev_min_reached"===t.kind?(n=r(t.when),l=t.values?.kwh):"ev_deadline"===t.kind&&(o=r(t.when));const c=n??o;return null==a&&null==c&&null==o?null:{plan:null!=a&&null!=c&&c>a?[{start:a,end:c,kwh:l}]:[],deadlineFrac:o,minReachedFrac:n}}_getSolarIntensity(){const t=this._stateObj("forecast_peak_time_today")?.state||this._stateObj("peak_time_today")?.state,e=parseFloat(this._stateObj("forecast_today_kwh")?.state||this._stateObj("forecast_today")?.state);if(!t||isNaN(e)||e<.5)return null;const s=Ne(t.slice(0,5));if(null==s)return null;const i=new Array(24).fill(0);for(let t=0;t<24;t++){const e=t/24-s,r=Math.exp(-e*e/(.26*.13));i[t]=r}const r=Math.max(...i);return i.map(t=>t/r)}_isEvCharging(){const t=parseFloat(this._stateObj("ev_power")?.state);if(!isNaN(t)&&t>10)return!0;const e=this._stateObj("charging_state")?.state;return e&&"charging"===e.toLowerCase()}_getNowBadges(){const t=this._stateObj("tariff_price_level")?.state,e=["cheap","normal","expensive","very_cheap","very_expensive"].includes(t)?t:null,s=["active","target_reached"].includes(this._stateObj("night_charging_status")?.state),i=parseFloat(this._stateObj("solar_power")?.state),r=!isNaN(i)&&i>50?`${(i/1e3).toFixed(1)} kW`:null,a=this._isEvCharging(),n=this._getEvPlanWindow();return{tariff:e,night:s?"now":null,surplus:r,ev:a?"charging":n?.plan?.length?"planned":null}}_buildSvgContent(t){const e=pt,s=t.textSec||"#888",i=t.textTertiary||"#777",r=t.surface||"rgba(255,255,255,0.03)";let a="";for(let t=0;t<=24;t+=2){const e=Ee(t/24);a+=`<text x="${e}" y="12" text-anchor="middle" fill="${s}"\n                font-size="10" font-family="'Segoe UI','Roboto',sans-serif"\n                font-variant-numeric="tabular-nums">${t.toString().padStart(2,"0")}</text>`}[this._t("tariff"),this._t("night"),this._t("surplus"),this._t("ev")].forEach((t,e)=>{a+=`<text x="32" y="${De+22*e+9+3.5}" text-anchor="end" fill="${i}"\n                font-size="10" font-family="'Segoe UI','Roboto',sans-serif">${t}</text>`});for(let t=0;t<4;t++){a+=`<rect x="36" y="${De+22*t}" width="556" height="18" rx="3" fill="${r}"/>`}const n={cheap:{fill:"#66bb6a",opacity:.62},normal:{fill:e.solar,opacity:.55},expensive:{fill:"#e91e63",opacity:.9},[xe]:{fill:"#9e9e9e",opacity:.35},[$e]:{fill:"#9e9e9e",opacity:.35}},o={cheap:"cheap",normal:"normal",expensive:"expensive",[xe]:"price_level_flat",[$e]:"price_level_no_prices"};for(const t of this._getTariffSchedule()){const e=Ee(t.start),s=Ee(t.end)-e,i=n[t.level]||n.normal,r=!0===t.isFallback,l=r?.35*i.opacity:i.opacity,c=r?` stroke="${i.fill}" stroke-width="1" stroke-opacity="0.6" stroke-dasharray="3,2"`:"",d=r?`${t.level} (no per-hour data — showing current level)`:null!=t.avgPrice?`${t.level} · avg ${t.avgPrice.toFixed(2)}`:t.level;if(a+=`<rect x="${e}" y="20" width="${s}" height="18"\n                rx="3" fill="${i.fill}" opacity="${l}"${c}>\n                <title>${d}</title></rect>`,s>30){const i=t.level&&o[t.level]?o[t.level]:t.type.toLowerCase();a+=`<text x="${e+s/2}" y="32.5" text-anchor="middle"\n                    fill="rgba(255,255,255,0.92)" font-size="9" font-weight="600"\n                    font-family="'Segoe UI','Roboto',sans-serif">${this._t(i)}</text>`}}const l=this._getNightWindow();if(l){const t=t=>{const e=Math.round(24*t*60);return`${String(Math.floor(e/60)).padStart(2,"0")}:${String(e%60).padStart(2,"0")}`},e=`${this._t("night")} ${t(l.start)}–${t(l.end)}`;if(l.start>l.end){const t=Ee(l.start);a+=`<rect x="${t}" y="42" width="${Ee(1)-t}"\n                    height="18" rx="3" fill="#42a5f5" opacity="0.55"><title>${e}</title></rect>`,a+=`<rect x="${Ee(0)}" y="42"\n                    width="${Ee(l.end)-Ee(0)}" height="18"\n                    rx="3" fill="#42a5f5" opacity="0.55"><title>${e}</title></rect>`}else{const t=Ee(l.start),s=Ee(l.end)-t;a+=`<rect x="${t}" y="42" width="${s}" height="18"\n                    rx="3" fill="#42a5f5" opacity="0.55"><title>${e}</title></rect>`}}const c=this._getSolarIntensity(),d=parseFloat(this._stateObj("forecast_today_kwh")?.state||NaN);if(c){const t=isNaN(d)?this._t("surplus"):`${this._t("surplus")} · forecast ${d.toFixed(1)} kWh`;for(let e=0;e<24;e++){const s=c[e];if(s<.08)continue;const i=Ee(e/24),r=Ee(1/24);a+=`<rect x="${i}" y="64" width="${r}" height="18"\n                    fill="#fdd835" opacity="${(.55*s).toFixed(2)}"><title>${t}</title></rect>`}}const p=this._getPredictedSurplusWindow();if(p){const t=Ee(p.start),e=Math.max(0,Ee(p.end)-t);a+=`<rect x="${t}" y="64" width="${e}" height="18"\n                rx="3" fill="none" stroke="#fdd835" stroke-width="1"\n                stroke-opacity="0.5" stroke-dasharray="2,2"/>`}for(const t of this._getSurplusBlocks()){const e=Ee(t.start),s=Math.max(0,Ee(t.end)-e);a+=`<rect x="${e}" y="64" width="${s}" height="18"\n                rx="3" fill="#fdd835" opacity="0.62"/>`}const _=this._getEvPlanWindow();if(_?.plan?.length)for(const t of _.plan){const s=Ee(t.start),i=Math.max(0,Ee(t.end)-s),r=t.kwh?`${this._t("plan_ev_charge_start")} → ${this._t("plan_ev_min_reached").replace("{kwh}",t.kwh)}`:this._t("plan_ev_charge_start");a+=`<rect x="${s}" y="86" width="${i}" height="18"\n                    rx="3" fill="${e.ev}" opacity="0.30"\n                    stroke="${e.ev}" stroke-width="0.6" stroke-opacity="0.6"\n                    stroke-dasharray="3,2"><title>${r}</title></rect>`}for(const t of this._getEvBlocks()){const s=Ee(t.start),i=Math.max(0,Ee(t.end)-s);a+=`<rect x="${s}" y="86" width="${i}" height="18"\n                rx="3" fill="${e.ev}" opacity="0.55"/>`}if(null!=_?.deadlineFrac){const t=Ee(_.deadlineFrac);a+=`<line x1="${t}" y1="84" x2="${t}" y2="106"\n                stroke="#f06292" stroke-width="1.2" stroke-dasharray="2,1" opacity="0.85">\n                <title>${this._t("plan_ev_deadline")}</title></line>`}if(this._isEvCharging()){const t=new Date,s=(t.getHours()+t.getMinutes()/60)/24,i=.5/24,r=Math.max(0,s-i),n=Math.min(1,s+i),o=Ee(r),l=Ee(n)-o;a+=`<rect x="${o}" y="86" width="${l}" height="18"\n                rx="3" fill="${e.ev}" opacity="0.95"/>`}const h=new Date,u=Ee((h.getHours()+h.getMinutes()/60)/24);return a+=`<line x1="${u}" y1="18" x2="${u}" y2="104"\n            stroke="#ef5350" stroke-width="1.5" stroke-linecap="round" opacity="0.9"/>`,a+=`<polygon points="${u-3},18 ${u+3},18 ${u},22"\n            fill="#ef5350" opacity="0.9"/>`,a}render(){if(!this._hass||!this._config)return K;const t=this._theme(),e=t.dotColor||"rgba(128,128,128,0.04)",s=this._buildSvgContent(t),i=this._getNowBadges(),r={cheap:"#66bb6a",very_cheap:"#66bb6a",normal:"#ff9800",expensive:"#e91e63",very_expensive:"#e91e63",now:"#42a5f5",charging:"#8DC892",planned:"#8DC892"},a=(t,e)=>{if(!e)return K;const s=r[e]||"#888",i=/\d/.test(e)?e:this._t(e);return H`<span class="now-badge"
                style="color:${s};border-color:${s}55;background:${s}22">${i}</span>`};return H`
            <style>
                :host { display: block; }
                .wrap {
                    padding: 12px 14px 8px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 25%, rgba(150,202,238,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${e} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${t.text||"#e0e0e0"});
                }
                .timeline-svg { width: 100%; height: auto; }
                .now-row {
                    display: flex; align-items: center; gap: 10px;
                    font-size: 11px; color: var(--secondary-text-color, #999);
                    margin-top: 4px; flex-wrap: wrap;
                }
                .now-row .now-label {
                    font-weight: 600; opacity: 0.7; margin-right: 4px;
                }
                .now-row .row-pair {
                    display: inline-flex; align-items: center; gap: 4px;
                }
                .now-row .row-pair > span:first-child { opacity: 0.7; }
                .now-badge {
                    display: inline-block; padding: 1px 7px;
                    border-radius: 999px; border: 1px solid;
                    font-size: 11px; font-weight: 600;
                    text-transform: capitalize;
                }
                .legend {
                    display: flex; gap: 14px; flex-wrap: wrap;
                    margin-top: 6px; padding-top: 6px;
                    border-top: 1px dashed rgba(255,255,255,0.06);
                    font-size: 11px; color: var(--secondary-text-color, #888);
                }
                .legend .item {
                    display: inline-flex; align-items: center; gap: 4px;
                }
                .legend i {
                    width: 10px; height: 10px; border-radius: 2px;
                    display: inline-block;
                }
            </style>
            <ha-card>
                <div class="wrap">
                    <svg class="timeline-svg"
                        viewBox="0 0 ${600} ${112}"
                        preserveAspectRatio="xMidYMid meet"
                        role="img"
                        aria-label="24-hour schedule timeline"
                        .innerHTML=${s}>
                    </svg>
                    <div class="now-row" role="status">
                        <span class="now-label">${this._t("plan_now")}:</span>
                        <span class="row-pair"><span>${this._t("tariff")}</span>${a(0,i.tariff)}</span>
                        <span class="row-pair"><span>${this._t("night")}</span>${a(0,i.night)}</span>
                        <span class="row-pair"><span>${this._t("surplus")}</span>${a(0,i.surplus)}</span>
                        <span class="row-pair"><span>${this._t("ev")}</span>${a(0,i.ev)}</span>
                    </div>
                    <div class="legend">
                        <span class="item"><i style="background:#66bb6a"></i>${this._t("cheap")}</span>
                        <span class="item"><i style="background:${pt.solar}"></i>${this._t("normal")}</span>
                        <span class="item"><i style="background:#e91e63"></i>${this._t("expensive")}</span>
                        <span class="item"><i style="background:#42a5f5"></i>${this._t("night")}</span>
                        <span class="item"><i style="background:#fdd835"></i>${this._t("surplus")}</span>
                        <span class="item"><i style="background:${pt.ev}"></i>${this._t("ev")}</span>
                    </div>
                </div>
            </ha-card>
        `}getCardSize(){return 2}static getStubConfig(){return{}}},{type:"sem-schedule-card",name:"SEM Schedule",description:"24-hour timeline showing tariff, night window, surplus window, and EV charging periods",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-schedule-card"});const Ae=[{id:"autostart",entity:"number.sem_battery_auto_start_soc",icon:"mdi:play-circle",labelKey:"auto_start_soc",helpKey:"zone_help_autostart",color:"#4db6ac"},{id:"buffer",entity:"number.sem_battery_buffer_soc",icon:"mdi:shield-half-full",labelKey:"buffer_soc",helpKey:"zone_help_buffer",color:"#ff9800"},{id:"priority",entity:"number.sem_battery_priority_soc",icon:"mdi:shield-alert",labelKey:"priority_soc",helpKey:"zone_help_priority",color:"#f44336"}];kt("sem-battery-zones-card",class extends Lt{static get watchedEntities(){return Ae.map(t=>t.entity)}static get properties(){return{...super.properties,_showHelp:{state:!0}}}constructor(){super(),this._showHelp=!1}_toggleHelp(){this._showHelp=!this._showHelp}setConfig(t){super.setConfig(t)}_getDecimalsForZone(t){const e=this._hass?.states[t];return(e&&parseFloat(e.attributes.step)||1)<1?1:0}_renderZoneMarkers(t){return Ae.map(e=>{const s=this._state(e.entity);if(null==s)return K;const i=Math.max(0,Math.min(100,s));return H`
                <div class="zone-marker" style="left:${i}%">
                    <div class="zone-dot" style="background:${e.color};border-color:${t.isDark?"#1e232d":"#fff"}"></div>
                    <span class="zone-marker-label">${s.toFixed(0)}%</span>
                </div>
            `})}_renderDynamicFloor(){const t=this._hass?.states["sensor.sem_battery_spendable_kwh"]?.attributes||{};if("spending"!==t.phase)return K;const e=parseFloat(t.dynamic_floor_pct);if(null==e||isNaN(e))return K;const s=Math.max(0,Math.min(100,e));return H`
            <div class="dyn-floor" style="left:${s}%">
                <span class="dyn-floor-label">${this._t("tonight")} ${e.toFixed(0)}%</span>
            </div>
        `}_renderStepper(t,e){const s=this._state(t.entity),i=this._getDecimalsForZone(t.entity),r=this._t(t.labelKey),a=this._showHelp?this._t(t.helpKey):"";return H`
            <div class="stepper-cell">
                <div class="stepper-row">
                    <ha-icon icon="${t.icon}" style="--mdc-icon-size:18px;color:${t.color}"></ha-icon>
                    <span class="stepper-label">${r}</span>
                    <div class="stepper-controls">
                        <button
                            class="stepper-minus"
                            aria-label="Decrease ${r}"
                            @click=${()=>this._stepNumber(t.entity,-1)}
                            @pointerdown=${()=>this._startHold(t.entity,-1)}
                            @pointerup=${()=>this._stopHold(t.entity)}
                            @pointerleave=${()=>this._stopHold(t.entity)}
                        >−</button>
                        <span class="stepper-value">${Tt(s,i)}%</span>
                        <button
                            class="stepper-plus"
                            aria-label="Increase ${r}"
                            @click=${()=>this._stepNumber(t.entity,1)}
                            @pointerdown=${()=>this._startHold(t.entity,1)}
                            @pointerup=${()=>this._stopHold(t.entity)}
                            @pointerleave=${()=>this._stopHold(t.entity)}
                        >+</button>
                    </div>
                </div>
                ${this._showHelp?H`<div class="zone-help-text" style="border-left-color:${t.color}">${a}</div>`:K}
            </div>
        `}render(){if(!this._config)return K;const t=this._theme(),e=this._state(Ae[0].entity),s=this._state(Ae[1].entity),i=this._state(Ae[2].entity),r=`${this._t("auto_start_soc")} ${Tt(e,0)}% · ${this._t("buffer_word")} ${Tt(s,0)}% · ${this._t("priority_soc")} ${Tt(i,0)}%`;return H`
            <style>
                :host { display: block; contain: layout style paint; }
                .wrap {
                    padding: 16px;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 25%, rgba(77,182,172,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${t.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${t.text});
                }
                .header {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    margin-bottom: 12px;
                }
                .header-title {
                    font-size: 14px;
                    font-weight: 600;
                    color: #4db6ac;
                }
                .subtitle {
                    flex: 1;
                    text-align: right;
                    font-size: 12px;
                    color: var(--secondary-text-color, ${t.textSec});
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }
                .zone-bar-wrap {
                    margin: 0 0 14px;
                    padding: 0 4px;
                }
                .zone-bar {
                    position: relative;
                    height: 8px;
                    border-radius: 4px;
                    background: linear-gradient(90deg, #f44336 0%, #ff9800 30%, #4db6ac 60%, #488fc2 80%, #8DC892 100%);
                    opacity: 0.6;
                }
                /* (#778) tonight's computed floor — a line, not a dot:
                   the dots are settings, this is an answer. */
                .dyn-floor {
                    position: absolute;
                    top: -5px;
                    bottom: -5px;
                    width: 2px;
                    background: #ff9800;
                    border-radius: 1px;
                    pointer-events: none;
                }
                .dyn-floor-label {
                    position: absolute;
                    bottom: -19px;
                    left: 50%;
                    transform: translateX(-50%);
                    font-size: 10px;
                    font-weight: 500;
                    color: #ff9800;
                    white-space: nowrap;
                }

                .zone-marker {
                    position: absolute;
                    top: -6px;
                    transform: translateX(-50%);
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    transition: left 0.3s ease;
                }
                .zone-dot {
                    width: 10px;
                    height: 10px;
                    border-radius: 50%;
                    border: 2px solid;
                    box-shadow: 0 0 4px rgba(0,0,0,0.3);
                }
                .zone-marker-label {
                    font-size: 10px;
                    font-weight: 600;
                    margin-top: 2px;
                    color: var(--secondary-text-color, ${t.textSec});
                    font-variant-numeric: tabular-nums;
                }
                .stepper-grid {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 4px 16px;
                }
                .stepper-row {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    padding: 6px 0;
                }
                .stepper-label {
                    font-size: 12px;
                    font-weight: 500;
                    flex: 1;
                    min-width: 0;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }
                .stepper-controls {
                    display: flex;
                    align-items: center;
                    gap: 2px;
                    flex-shrink: 0;
                }
                .stepper-minus, .stepper-plus {
                    width: 28px;
                    height: 28px;
                    border-radius: 7px;
                    border: 1px solid ${t.surfaceBorder};
                    background: ${t.surface};
                    color: var(--primary-text-color, ${t.text});
                    font-size: 15px;
                    font-weight: 600;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    transition: background 0.15s;
                    user-select: none;
                    -webkit-user-select: none;
                    touch-action: manipulation;
                    padding: 0;
                    line-height: 1;
                }
                .stepper-minus:hover, .stepper-plus:hover {
                    background: ${t.surfaceHover};
                }
                .stepper-value {
                    font-size: 13px;
                    font-weight: 600;
                    min-width: 48px;
                    text-align: center;
                    font-variant-numeric: tabular-nums;
                }
                /* Help toggle in header (#sem-zone-help, 2026-06-06). Tap
                   the (?) to reveal one-line descriptions under each
                   stepper. Off by default — keeps the card compact. */
                .help-toggle {
                    cursor: pointer;
                    color: var(--secondary-text-color, ${t.textSec});
                    opacity: 0.7;
                    flex-shrink: 0;
                    transition: opacity 0.15s, color 0.15s;
                    user-select: none;
                    -webkit-user-select: none;
                }
                .help-toggle:hover { opacity: 1; }
                .help-toggle.on { color: #4db6ac; opacity: 1; }
                .stepper-cell { display: flex; flex-direction: column; }
                .zone-help-text {
                    font-size: 11px;
                    line-height: 1.35;
                    color: var(--secondary-text-color, ${t.textSec});
                    opacity: 0.8;
                    padding: 4px 6px 6px 36px;
                    border-left: 2px solid;
                    margin-left: 9px;
                    margin-top: -2px;
                    margin-bottom: 4px;
                }
                @media (max-width: 480px) {
                    .stepper-grid { grid-template-columns: 1fr; }
                }
            </style>
            <div class="wrap">
                <div class="header">
                    <ha-icon icon="mdi:battery-charging-medium" style="--mdc-icon-size:18px;color:#4db6ac"></ha-icon>
                    <span class="header-title">${this._t("soc_zones")}</span>
                    <span class="subtitle">${r}</span>
                    <ha-icon
                        class="help-toggle ${this._showHelp?"on":""}"
                        icon="${this._showHelp?"mdi:help-circle":"mdi:help-circle-outline"}"
                        title="${this._t("zone_help_toggle")}"
                        @click=${()=>this._toggleHelp()}
                        style="--mdc-icon-size:18px"
                    ></ha-icon>
                </div>
                <div class="zone-bar-wrap">
                    <div class="zone-bar">
                        ${this._renderZoneMarkers(t)}
                        ${this._renderDynamicFloor()}
                    </div>
                </div>
                <div class="stepper-grid">
                    ${Ae.map(e=>this._renderStepper(e,t))}
                </div>
            </div>
        `}getCardSize(){return 4}static getStubConfig(){return{}}},{type:"sem-battery-zones-card",name:"SEM Battery Zones Card",description:"The three battery SOC thresholds — priority, buffer and auto-start",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-battery-zones-card",preview:!1});const Te="sensor.sem_",Ie=["daily_costs","daily_savings","daily_export_revenue","daily_battery_savings","daily_net_cost","monthly_costs","monthly_savings","monthly_export_revenue","monthly_net_cost","monthly_battery_savings","yearly_costs","yearly_savings","yearly_export_revenue","yearly_net_cost","yearly_battery_savings","lifetime_total_savings","roi_percentage","roi_payback_years","roi_annual_savings","daily_co2_avoided","yearly_co2_avoided","lifetime_co2_avoided","yearly_trees_equivalent","lifetime_trees_equivalent"];kt("sem-costs-card",class extends Lt{static get watchedEntities(){return Ie.map(t=>`${Te}${t}`)}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||Te}_val(t,e=null){return At(this._hass?.states[`${this._prefix}${t}`])??e}_fmt(t,e=2){return null==t||isNaN(t)?"—":t.toFixed(e)}_fmtCurr(t,e,s=2){return null==t||isNaN(t)?"—":t.toFixed(s)+" "+e}_netColor(t){return null==t?"var(--secondary-text-color, #888)":t<=0?"#8DC892":"#f06292"}_renderPeriodSection(t,e,s,i,r){const a=this._val(`${t}_costs`),n=this._val(`${t}_savings`),o=this._val(`${t}_battery_savings`),l=this._val(`${t}_export_revenue`),c=this._val(`${t}_net_cost`),d=this._netColor(c),p=null==c?Nt:(c<=0?"+":"")+this._fmtCurr(Math.abs(c),i),_=this._hass?.states[`${this._prefix}${t}_battery_savings`]?o:0,h=null==n||null==_?null:n+_;return H`
            <div class="section">
                <div class="section-title">${this._t(e)}</div>

                <div class="block-title">${this._t("cost_block_moved")}</div>
                <div class="metric-row">
                    <span class="metric-label">${this._t("import_cost")}</span>
                    <span class="metric-val c-import">${this._fmtCurr(a,i)}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">${this._t("export_revenue")}</span>
                    <span class="metric-val c-export">${this._fmtCurr(l,i)}</span>
                </div>
                <div class="metric-row net-row">
                    <span class="metric-label"><strong>${this._t(c<=0?"net_saving":"net_cost")}</strong></span>
                    <span class="metric-val" style="color:${d}">${p}</span>
                </div>

                <div class="block-title">${this._t("cost_block_avoided")}</div>
                <div class="metric-row">
                    <span class="metric-label">${this._t("solar_savings")}</span>
                    <span class="metric-val c-solar">${this._fmtCurr(n,i)}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">${this._t("battery_savings")}</span>
                    <span class="metric-val c-battery">${this._fmtCurr(o,i)}</span>
                </div>
                <div class="metric-row net-row">
                    <span class="metric-label"><strong>${this._t("cost_block_avoided_total")}</strong></span>
                    <span class="metric-val c-solar">${this._fmtCurr(h,i)}</span>
                </div>

                <div class="block-note">${this._t("cost_block_note")}</div>
            </div>
        `}render(){if(!this._config||!this._hass)return K;const t=ft(this._hass),e=this._theme(),s=this._val("daily_net_cost"),i=s<=0,r=this._netColor(s),a=null==s?Nt:(i?"+":"")+this._fmt(Math.abs(s),2)+" "+t,n=i?this._t("net_saving_today"):this._t("net_cost_today"),o=this._val("roi_percentage"),l=o>=0?"#8DC892":"#f06292",c=this._val("roi_payback_years");return H`
            <ha-card>
                <div class="wrap">
                    <!-- Hero -->
                    <div class="hero">
                        <div class="hero-net" style="color:${r}">${a}</div>
                        <div class="hero-label" style="color:${r}">${n}</div>
                    </div>

                    <!-- Today / Monthly / Yearly (3 columns) -->
                    <div class="three-col">
                        ${this._renderPeriodSection("daily","today","d",t,e)}
                        ${this._renderPeriodSection("monthly","monthly","m",t,e)}
                        ${this._renderPeriodSection("yearly","yearly","y",t,e)}
                    </div>

                    <!-- ROI + Environmental (2 columns) -->
                    <div class="two-col">
                        <div class="section">
                            <div class="section-title">${this._t("roi")}</div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("lifetime_savings")}</span>
                                <span class="metric-val c-green">${this._fmtCurr(this._val("lifetime_total_savings"),t,0)}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("annual_savings")}</span>
                                <span class="metric-val c-green">${this._fmtCurr(this._val("roi_annual_savings"),t,0)}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("payback_years")}</span>
                                <span class="metric-val">${c>0?this._fmt(c,1)+" "+this._t("years"):"—"}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("roi_percentage")}</span>
                                <span class="metric-val" style="color:${l}">${null!=o?this._fmt(o,1)+"%":"—"}</span>
                            </div>
                        </div>
                        <div class="section">
                            <div class="section-title">${this._t("environment")}</div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("co2_today")}</span>
                                <span class="metric-val c-leaf">${this._fmt(this._val("daily_co2_avoided"),1)} ${this._kgUnit("daily_co2_avoided")}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("co2_yearly")}</span>
                                <span class="metric-val c-leaf">${this._fmt(this._val("yearly_co2_avoided"),0)} ${this._kgUnit("yearly_co2_avoided")}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("co2_lifetime")}</span>
                                <span class="metric-val c-leaf">${this._fmt(this._val("lifetime_co2_avoided"),0)} ${this._kgUnit("lifetime_co2_avoided")}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("trees_yearly")}</span>
                                <span class="metric-val c-leaf">${this._fmt(this._val("yearly_trees_equivalent"),1)}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("trees_lifetime")}</span>
                                <span class="metric-val c-leaf">${this._fmt(this._val("lifetime_trees_equivalent"),1)}</span>
                            </div>
                        </div>
                    </div>
                </div>
            </ha-card>
        `}static get styles(){return a`
            :host { display: block; }
            .wrap {
                padding: 16px 20px;
                position: relative;
                background:
                    radial-gradient(ellipse 70% 60% at 50% 25%, rgba(240,98,146,0.06) 0%, transparent 100%),
                    radial-gradient(circle at 2px 2px, rgba(128,128,128,0.05) 0.7px, transparent 0.7px);
                background-size: 100% 100%, 50px 50px;
                font-family: 'Segoe UI','Roboto',sans-serif;
                color: var(--primary-text-color, #e0e0e0);
            }

            /* ── Hero ── */
            .hero {
                display: flex; align-items: center; justify-content: center;
                flex-direction: column; padding: 4px 0 8px;
                text-align: center;
            }
            .hero-net {
                font-size: 28px; font-weight: 700;
                font-variant-numeric: tabular-nums;
                text-shadow: 0 0 12px rgba(141,200,146,0.3);
                line-height: 1.1;
            }
            .hero-label {
                font-size: 12px; font-weight: 500; text-transform: uppercase;
                letter-spacing: 0.6px; margin-top: 2px;
                color: var(--secondary-text-color, #999);
            }

            /* ── Section ── */
            .section {
                margin-top: 10px; padding: 10px 12px;
                background: var(--secondary-background-color, rgba(255,255,255,0.06));
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius: 10px;
            }
            .section-title {
                font-size: 12px; font-weight: 600; text-transform: uppercase;
                letter-spacing: 0.6px; color: #8DC892; margin-bottom: 6px;
            }

            /* ── Multi-column layouts ── */
            .three-col {
                display: grid;
                grid-template-columns: 1fr 1fr 1fr;
                gap: 0 10px;
            }
            .two-col {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 0 10px;
            }
            @media (max-width: 400px) {
                .three-col { grid-template-columns: 1fr; }
                .two-col { grid-template-columns: 1fr; }
            }

            /* ── Metric rows ── */
            .metric-row {
                display: flex; justify-content: space-between; align-items: baseline;
                padding: 2px 0;
            }
            .block-title {
                font-size: 12px; letter-spacing: .06em; text-transform: uppercase;
                opacity: .55; margin: 10px 0 2px;
            }
            .block-note {
                font-size: 12px; opacity: .55; margin-top: 8px; line-height: 1.35;
            }
            .net-row {
                margin-top: 4px; padding-top: 4px;
                border-top: 1px solid var(--divider-color, rgba(255,255,255,0.12));
            }
            .metric-label {
                font-size: 12px; color: var(--secondary-text-color, #999);
                font-weight: 500;
            }
            .metric-val {
                font-size: 12px; font-weight: 600;
                font-variant-numeric: tabular-nums;
                color: var(--primary-text-color, #e0e0e0);
            }

            /* Color helpers */
            .c-import  { color: #488fc2; }
            .c-solar   { color: #ff9800; }
            .c-battery { color: #4db6ac; }
            .c-export  { color: #8353d1; }
            .c-green   { color: #8DC892; }
            .c-leaf    { color: #8DC892; }
        `}getCardSize(){return 5}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"sem-costs-card",name:"SEM Costs",description:"Consolidated financial card with daily/monthly/yearly costs, savings, ROI, and environmental impact",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-costs-card"});const Re="sensor.sem_",Be=[{id:"ev_econ",icon:"mdi:car-electric",color:"#8DC892",titleKey:"ev_charging_economics"},{id:"investment",icon:"mdi:bank",color:"#96CAEE",titleKey:"system_investment_cost"},{id:"demand",icon:"mdi:flash-triangle",color:"#ff9800",titleKey:"demand_charge"},{id:"tariff",icon:"mdi:tag-multiple",color:"#488fc2",titleKey:"tariff_rates"}];kt("sem-costs-detail-card",class extends Lt{static get watchedEntities(){return[`${Re}lifetime_ev_energy`,`${Re}lifetime_ev_cost`,`${Re}lifetime_ev_solar_share`,`${Re}lifetime_ev_battery_share`,`${Re}lifetime_ev_grid_share`,"number.sem_system_investment_cost",`${Re}monthly_consecutive_peak`,`${Re}power_charge_cost`,"number.sem_demand_charge_rate",`${Re}tariff_current_import_rate`,`${Re}tariff_current_export_rate`,`${Re}tariff_price_level`,"number.sem_electricity_import_rate","number.sem_electricity_export_rate"]}constructor(){super(),this._collapsed={}}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||Re}_val(t,e=null){return At(this._hass?.states[`${this._prefix}${t}`])??e}_valStr(t){const e=this._hass?.states[`${this._prefix}${t}`];return e&&"unavailable"!==e.state&&"unknown"!==e.state?e.state:""}_numVal(t,e=null){const s=this._frozenEntities[t];return s?s.value:At(this._hass?.states[t])??e}_evModule(){return!!this._hass?.states[`${this._prefix}lifetime_ev_energy`]}_entityExists(t){const e=this._hass?.states[t];return!(!e||"unavailable"===e.state||"unknown"===e.state)}_toggleSection(t){this._collapsed={...this._collapsed,[t]:!this._collapsed[t]},this.requestUpdate()}_sectionSubtitle(t,e){if("ev_econ"===t){const t=this._val("lifetime_ev_energy");if(!this._evModule())return this._t("no_ev_data");if(null==t)return Nt;if(t<=0)return this._t("no_ev_data");const s=this._val("lifetime_ev_cost"),i=this._val("lifetime_ev_solar_share");return`${Tt(null==s?null:s/t,2)} ${e}/kWh · ${Tt(i,0)}% ${this._t("solar_word")}`}if("investment"===t){const t=this._numVal("number.sem_system_investment_cost");return t>0?`${t.toFixed(0)} ${e}`:""}if("demand"===t){const t=this._val("monthly_consecutive_peak"),s=this._val("power_charge_cost");return`${Tt(t,1)} kW · ${Tt(s,2)} ${e}`}if("tariff"===t){const t=this._val("tariff_current_import_rate"),s=this._valStr("tariff_price_level");return s?`${Tt(t,4)} ${e} · ${this._t(ke(s))}`:`${Tt(t,4)} ${e}`}return""}_renderTypedStepper(t,e){const s=this._hass?.states[t],i=this._numVal(t),r=s?.attributes?.unit_of_measurement||"";return H`
            <div class="stepper-row">
                <span class="stepper-label">${this._t(e)}</span>
                <div class="stepper-controls">
                    <button class="stepper-minus" aria-label="Decrease"
                        @click=${()=>this._stepNumber(t,-1)}>−</button>
                    <input class="stepper-input" type="number"
                        .value=${null==i?"":String(i)}
                        @change=${e=>{const s=parseFloat(e.target.value);Number.isNaN(s)||this._setNumber(t,s)}}
                        @keydown=${t=>{"Enter"===t.key&&t.target.blur()}}>
                    ${r?H`<span class="stepper-unit">${r}</span>`:K}
                    <button class="stepper-plus" aria-label="Increase"
                        @click=${()=>this._stepNumber(t,1)}>+</button>
                </div>
            </div>
        `}_renderStepper(t,e){const s=this._hass?.states[t],i=this._numVal(t),r=s&&parseFloat(s.attributes.step)||1,a=s?.attributes?.unit_of_measurement||"",n=Tt(i,r<1?2:0)+(a?" "+a:"");return H`
            <div class="stepper-row">
                <span class="stepper-label">${this._t(e)}</span>
                <div class="stepper-controls">
                    <button
                        class="stepper-minus"
                        aria-label="Decrease"
                        @click=${()=>this._stepNumber(t,-1)}
                        @pointerdown=${()=>this._startHold(t,-1)}
                        @pointerup=${()=>this._stopHold(t)}
                        @pointerleave=${()=>this._stopHold(t)}
                    >−</button>
                    <span class="stepper-value">${n}</span>
                    <button
                        class="stepper-plus"
                        aria-label="Increase"
                        @click=${()=>this._stepNumber(t,1)}
                        @pointerdown=${()=>this._startHold(t,1)}
                        @pointerup=${()=>this._stopHold(t)}
                        @pointerleave=${()=>this._stopHold(t)}
                    >+</button>
                </div>
            </div>
        `}_renderInfoTile(t,e,s,i){return H`
            <div class="info-tile">
                <ha-icon icon="${t}" style="--mdc-icon-size:18px;color:${e}"></ha-icon>
                <div class="info-tile-content">
                    <span class="info-tile-label">${this._t(s)}</span>
                    <span class="info-tile-value">${i}</span>
                </div>
            </div>
        `}_renderSectionBody(t,e){if("ev_econ"===t){const t=this._val("lifetime_ev_energy");if(!this._evModule()||null!=t&&t<=0)return H`<div class="info-empty">${this._t("no_ev_data")}</div>`;const s=this._val("lifetime_ev_cost"),i=this._val("lifetime_ev_solar_share"),r=this._val("lifetime_ev_battery_share"),a=this._val("lifetime_ev_grid_share"),n=null==s||null==t?null:s/t;return H`
                <div class="info-tiles">
                    ${this._renderInfoTile("mdi:currency-usd","#8DC892","cost_per_kwh",Tt(n,4)+" "+e+"/kWh")}
                    ${this._renderInfoTile("mdi:solar-power","#ff9800","solar_share",Tt(i,1)+"%")}
                    ${this._renderInfoTile("mdi:battery-arrow-down","#4db6ac","battery_share",Tt(r,1)+"%")}
                    ${this._renderInfoTile("mdi:transmission-tower","#488fc2","grid_share",Tt(a,1)+"%")}
                </div>
            `}if("investment"===t)return H`${this._renderTypedStepper("number.sem_system_investment_cost","system_investment_cost")}`;if("demand"===t){const t=this._val("monthly_consecutive_peak"),s=this._val("power_charge_cost");return H`
                <div class="info-tiles">
                    ${this._renderInfoTile("mdi:chart-bell-curve","#ff9800","monthly_peak",Tt(t,2)+" kW")}
                    ${this._renderInfoTile("mdi:currency-usd","#f06292","demand_charge",Tt(s,2)+" "+e)}
                </div>
                ${this._renderStepper("number.sem_demand_charge_rate","demand_charge_rate")}
            `}if("tariff"===t){const t=this._hass?.states["sensor.sem_tariff_current_import_rate"],s=this._hass?.states["sensor.sem_tariff_current_export_rate"],i=Ft(t)?Nt:t.state,r=t?.attributes?.unit_of_measurement||e,a=Ft(s)?Nt:s.state,n=s?.attributes?.unit_of_measurement||e,o=this._valStr("tariff_price_level"),l=this._entityExists("number.sem_electricity_import_rate"),c=this._entityExists("number.sem_electricity_export_rate");return H`
                <div class="info-tiles tariff-info-tiles">
                    ${this._renderInfoTile("mdi:transmission-tower-import","#488fc2","current_import_rate",`${i} ${r}`)}
                    ${this._renderInfoTile("mdi:transmission-tower-export","#8353d1","current_export_rate",`${a} ${n}`)}
                    ${this._renderInfoTile("mdi:signal-cellular-outline","#96CAEE","price_level",o?this._t(ke(o)):"—")}
                </div>
                ${l?this._renderStepper("number.sem_electricity_import_rate","current_import_rate"):K}
                ${c?this._renderStepper("number.sem_electricity_export_rate","current_export_rate"):K}
            `}return K}_renderSection(t,e){const s=this._collapsed[t.id],i=this._sectionSubtitle(t.id,e);return H`
            <div class="section">
                <div
                    class="section-header"
                    tabindex="0"
                    role="button"
                    aria-expanded="${!s}"
                    @click=${()=>this._toggleSection(t.id)}
                    @keydown=${e=>{"Enter"!==e.key&&" "!==e.key||(e.preventDefault(),this._toggleSection(t.id))}}
                >
                    <ha-icon icon="${t.icon}" style="--mdc-icon-size:20px;color:${t.color}"></ha-icon>
                    <span class="section-title-text">${this._t(t.titleKey)}</span>
                    <span class="section-subtitle">${i}</span>
                    <ha-icon
                        class="chevron"
                        icon="mdi:chevron-down"
                        style="--mdc-icon-size:18px;transform:rotate(${s?"-90deg":"0deg"});transition:transform 0.25s ease"
                    ></ha-icon>
                </div>
                ${s?K:H`
                    <div class="section-body">
                        ${this._renderSectionBody(t.id,e)}
                    </div>
                `}
            </div>
        `}render(){if(!this._config||!this._hass)return K;const t=ft(this._hass);return H`
            <div class="wrap">
                ${Be.map(e=>this._renderSection(e,t))}
            </div>
        `}static get styles(){return a`
            :host { display: block; }
            .wrap {
                padding: 16px;
                position: relative;
                background:
                    radial-gradient(ellipse 70% 60% at 50% 25%, rgba(240,98,146,0.06) 0%, transparent 100%),
                    radial-gradient(circle at 2px 2px, rgba(128,128,128,0.05) 0.7px, transparent 0.7px);
                background-size: 100% 100%, 50px 50px;
                font-family: 'Segoe UI','Roboto',sans-serif;
                color: var(--primary-text-color, #e0e0e0);
            }

            /* ── Sections ── */
            .section {
                margin-bottom: 8px;
                border-radius: 14px;
                background: var(--secondary-background-color, rgba(255,255,255,0.06));
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                overflow: hidden;
                transition: border-color 0.2s;
            }
            .section:hover {
                border-color: rgba(255,255,255,0.18);
            }

            .section-header {
                display: flex; align-items: center; gap: 8px;
                padding: 12px 14px;
                cursor: pointer;
                user-select: none;
                -webkit-user-select: none;
                transition: background 0.15s;
            }
            .section-header:hover {
                background: rgba(255,255,255,0.10);
            }
            .section-title-text {
                font-size: 14px; font-weight: 600;
                white-space: nowrap;
            }
            .section-subtitle {
                flex: 1;
                font-size: 12px;
                color: var(--secondary-text-color, #999);
                text-align: right;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
                margin-right: 4px;
            }

            .section-body {
                padding: 0 14px 14px;
                overflow: hidden;
            }

            /* ── Number Stepper ── */
            .stepper-row {
                display: flex; align-items: center; justify-content: space-between;
                padding: 7px 0;
            }
            .stepper-label {
                font-size: 13px; font-weight: 500;
                flex: 1; min-width: 0;
                overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
            }
            .stepper-controls {
                display: flex; align-items: center; gap: 2px;
                flex-shrink: 0;
            }
            .stepper-minus, .stepper-plus {
                width: 30px; height: 30px;
                border-radius: 8px;
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                background: var(--secondary-background-color, rgba(255,255,255,0.06));
                color: var(--primary-text-color, #e0e0e0);
                font-size: 16px; font-weight: 600;
                cursor: pointer;
                display: flex; align-items: center; justify-content: center;
                transition: background 0.15s, border-color 0.15s;
                user-select: none;
                -webkit-user-select: none;
                touch-action: manipulation;
                padding: 0; line-height: 1;
            }
            .stepper-minus:hover, .stepper-plus:hover {
                background: rgba(255,255,255,0.10);
                border-color: var(--primary-color, #42a5f5);
            }
            .stepper-input {
                width: 110px; text-align: center;
                background: transparent; border: 1px solid rgba(150,202,238,0.35);
                border-radius: 6px; color: inherit; font: inherit;
                padding: 3px 6px; -moz-appearance: textfield;
            }
            .stepper-input::-webkit-outer-spin-button,
            .stepper-input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
            .stepper-unit { font-size: 12px; opacity: 0.75; }
            .stepper-value {
                font-size: 13px; font-weight: 600;
                min-width: 60px; text-align: center;
                font-variant-numeric: tabular-nums;
            }

            /* ── Info tiles ── */
            .info-tiles {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 8px;
                margin: 8px 0;
            }
            .tariff-info-tiles {
                grid-template-columns: 1fr 1fr 1fr;
            }
            @media (max-width: 480px) {
                .info-tiles { grid-template-columns: 1fr; }
                .tariff-info-tiles { grid-template-columns: 1fr 1fr; }
            }
            .info-tile {
                display: flex; align-items: flex-start; gap: 8px;
                padding: 10px;
                border-radius: 10px;
                background: rgba(255,255,255,0.03);
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
            }
            .info-tile ha-icon { margin-top: 1px; flex-shrink: 0; }
            .info-tile-content { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
            .info-tile-label {
                font-size: 11px; font-weight: 500; text-transform: uppercase;
                color: var(--secondary-text-color, #999);
                letter-spacing: 0.3px;
                white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
            }
            .info-tile-value {
                font-size: 13px; font-weight: 600;
                font-variant-numeric: tabular-nums;
            }

            /* ── EV no data ── */
            .info-empty {
                font-size: 13px;
                color: var(--secondary-text-color, #999);
                text-align: center;
                padding: 12px 0;
                font-style: italic;
            }
        `}getCardSize(){return 8}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"sem-costs-detail-card",name:"SEM Costs Detail Card",description:"Financial details — EV economics, investment, demand charge, and tariff rates",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-costs-detail-card",preview:!1});const Oe="sensor.sem_";kt("sem-charger-status-card",class extends Lt{constructor(){super(),this._chargers=[],this._lastStateCount=0}set hass(t){this._hass,this._hass=t;const e=t?.language,s="function"==typeof semLocalize;let i=!1;if((e!==this._lang||s&&!this._localizeReady)&&(this._lang=e,this._localizeReady=s,i=!0),this._isFrozen()&&!i)return;if(this._chargers?.length>0&&!i){const e=this._config?.entity_prefix||Oe;if(Rt(t.states,this._chargers.map(t=>`${e}charger_${t}_power`)))return}const r=Object.keys(t.states).length;if(r!==this._lastStateCount){this._lastStateCount=r;const e=[];for(const s of Object.keys(t.states)){if(s.includes("_flow_"))continue;const t=s.match(/^sensor\.sem_charger_(.+)_power$/);t&&e.push(t[1])}this._chargers=e}const a=this._config?.entity_prefix||Oe,n=this._chargers.map(e=>[`charger_${e}_power`,`charger_${e}_session_energy`,`charger_${e}_session_solar_share`,`charger_${e}_taper_trend`].map(e=>t.states[`${a}${e}`]?.state||"").join(":")).join("|");(n!==this._lastKey||i)&&(this._lastKey=n,this._scheduleUpdate())}get hass(){return this._hass}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||Oe}_val(t,e=null){return At(this._hass?.states[`${this._prefix}${t}`])??e}_valStr(t){const e=this._hass?.states[`${this._prefix}${t}`];return e&&"unavailable"!==e.state&&"unknown"!==e.state?e.state:""}_chargerName(t){const e=this._hass?.states[`${this._prefix}charger_${t}_power`];let s=t.replace(/_/g," ").replace(/\b\w/g,t=>t.toUpperCase());return e?.attributes?.charger_name?e.attributes.charger_name:(e?.attributes?.friendly_name&&(s=e.attributes.friendly_name.replace(/^SEM\s+/i,"").replace(/\s+Power$/i,"")),s)}_renderChargerTile(t){const e=this._val(`charger_${t}_power`),s=this._val(`charger_${t}_session_energy`),i=this._val(`charger_${t}_session_solar_share`),r=this._valStr(`charger_${t}_taper_trend`)||"stable",a=this._t(r),n=this._chargerName(t),o=e>50,l=o?"#8DC892":"#888",c=null==e?Nt:o?this._t("charging"):this._t("idle");return H`
            <div class="charger-tile">
                <div class="charger-glow" style="opacity:${o?"0.15":"0"}"></div>
                <div class="charger-header">
                    <ha-icon icon="mdi:ev-station" style="--mdc-icon-size:20px;color:${l}"></ha-icon>
                    <span class="charger-name">${n}</span>
                    <span class="charger-status" style="color:${l}">${c}</span>
                </div>
                <div class="charger-metrics">
                    <div class="metric">
                        <span class="metric-value">${Tt(e,0)}</span>
                        <span class="metric-unit">W</span>
                        <span class="metric-label">${this._t("power")}</span>
                    </div>
                    <div class="metric">
                        <span class="metric-value">${Tt(s,1)}</span>
                        <span class="metric-unit">kWh</span>
                        <span class="metric-label">${this._t("session")}</span>
                    </div>
                    <div class="metric">
                        <span class="metric-value">${Tt(i,0)}</span>
                        <span class="metric-unit">%</span>
                        <span class="metric-label">${this._t("solar")}</span>
                    </div>
                    <div class="metric">
                        <span class="metric-value taper-${r}">${a}</span>
                        <span class="metric-label">${this._t("taper")}</span>
                    </div>
                </div>
            </div>
        `}render(){return this._config&&this._hass?H`
            <div class="card-wrap">
                <div class="card-title">${this._t("charger_status")}</div>
                <div class="card-subtitle">${this._chargers.length} ${this._t("chargers_configured")}</div>
                <div class="charger-grid">
                    ${this._chargers.map(t=>this._renderChargerTile(t))}
                </div>
            </div>
        `:K}static get styles(){return a`
            :host { display: block; }
            .card-wrap {
                padding: 16px;
                position: relative;
            }
            .card-title {
                font-size: 1.1em;
                font-weight: 500;
                color: var(--primary-text-color, #e0e0e0);
                margin-bottom: 4px;
            }
            .card-subtitle {
                font-size: 0.85em;
                color: var(--secondary-text-color, #999);
                margin-bottom: 16px;
            }
            .charger-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
                gap: 12px;
            }
            .charger-tile {
                position: relative;
                background: var(--secondary-background-color, rgba(255,255,255,0.06));
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius: 12px;
                padding: 14px;
                overflow: hidden;
            }
            .charger-glow {
                position: absolute;
                top: -20px; right: -20px;
                width: 80px; height: 80px;
                border-radius: 50%;
                background: radial-gradient(circle, rgba(141,200,146,0.4), transparent 70%);
                pointer-events: none;
                transition: opacity 0.5s ease;
            }
            .charger-header {
                display: flex;
                align-items: center;
                gap: 8px;
                margin-bottom: 12px;
            }
            .charger-name {
                flex: 1;
                font-weight: 500;
                color: var(--primary-text-color, #e0e0e0);
                font-size: 0.95em;
            }
            .charger-status {
                font-size: 0.8em;
                font-weight: 500;
                text-transform: uppercase;
                letter-spacing: 0.05em;
            }
            .charger-metrics {
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 8px;
                text-align: center;
            }
            .metric-value {
                display: block;
                font-size: 1.15em;
                font-weight: 600;
                color: var(--primary-text-color, #e0e0e0);
            }
            .metric-unit {
                font-size: 0.8em;
                color: var(--secondary-text-color, #999);
                margin-left: 1px;
            }
            .metric-label {
                display: block;
                font-size: 0.8em;
                color: var(--secondary-text-color, #999);
                margin-top: 2px;
                text-transform: uppercase;
                letter-spacing: 0.03em;
            }
            .taper-rising  { color: #f06292; }
            .taper-falling { color: #8DC892; }
            .taper-stable  { color: var(--secondary-text-color, #999); }
        `}getCardSize(){return Math.max(2,this._chargers.length)}static getStubConfig(){return{}}},{type:"sem-charger-status-card",name:"SEM Charger Status",description:"Multi-charger status display with per-charger tiles",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-charger-status-card"});const Le="sem-next";kt("sem-next-link-card",class extends Lt{static get properties(){return{_exists:{state:!0},_busy:{state:!0}}}constructor(){super(),this._exists=null,this._busy=!1}set hass(t){const e=!this._hass;super.hass=t,e&&t&&this._refresh()}get hass(){return this._hass}async _refresh(){try{const t=await this._hass.callWS({type:"lovelace/dashboards/list"});this._exists=Array.isArray(t)&&t.some(t=>t.url_path===Le)}catch(t){this._exists=null}}async _create(){if(!this._busy){this._busy=!0;try{await this._hass.callService("solar_energy_management","generate_dashboard",{template:"next"}),setTimeout(()=>{this._refresh(),this._busy=!1},4e3)}catch(t){this._busy=!1}}}static get styles(){return a`
            :host { display: block; }
            .row { display: flex; align-items: center; gap: 14px; padding: 14px 18px; flex-wrap: wrap; }
            .icon { width: 44px; height: 44px; border-radius: 12px; display: grid; place-items: center;
                    background: rgba(31, 122, 140, 0.14); }
            .icon ha-icon { color: #4FB3C4; --mdc-icon-size: 26px; }
            .text { flex: 1 1 200px; min-width: 0; }
            .title { font-weight: 700; font-size: 1rem; }
            .sub { font-size: 0.85rem; color: var(--secondary-text-color); }
            .btn { border: 1px solid var(--divider-color); background: var(--secondary-background-color);
                   color: var(--primary-text-color); font: 600 13px inherit; padding: 10px 16px; border-radius: 12px;
                   cursor: pointer; min-height: 40px; text-decoration: none; display: inline-flex; align-items: center; }
            .btn.primary { background: #1F7A8C; color: #fff; border-color: transparent; }
            .btn[disabled] { opacity: 0.6; cursor: default; }
        `}render(){return this._hass?H`
            <ha-card>
                <div class="row">
                    <div class="icon"><ha-icon icon="mdi:view-dashboard-variant-outline"></ha-icon></div>
                    <div class="text">
                        <div class="title">${this._t("next_link_title")}</div>
                        <div class="sub">${this._t("next_link_sub")}</div>
                    </div>
                    ${this._exists?H`<a class="btn primary" href="/${Le}/now">${this._t("next_link_open")}</a>`:H`<button class="btn primary" ?disabled=${this._busy} @click=${()=>this._create()}>
                                   ${this._busy?this._t("next_link_creating"):this._t("next_link_create")}
                               </button>`}
                </div>
            </ha-card>
        `:K}getCardSize(){return 1}static getStubConfig(){return{}}},{type:"sem-next-link-card",name:"SEM Next link",description:"Create or open the SEM Next dashboard beside the classic one",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-next-link-card",preview:!0});const Pe=100;function Ue(t){return Number.isFinite(t)?(Math.round(10*t)/10).toFixed(1):""}function We(t){return Number.isFinite(t)?String(Math.round(t)):""}function He(t,e,s){let i=String(t||"");for(const[t,r]of Object.entries(e||{})){const e=r&&"object"==typeof r&&r.key?He(s(r.key),r.params,s):String(r??"");i=i.split("{"+t+"}").join(e)}return i}function je(t,e){let s=0;for(const i of Array.isArray(t)?t:[]){if(!e(i.id))continue;const t=Date.parse(i.start),r=Date.parse(i.end);!Number.isFinite(t)||!Number.isFinite(r)||r<=t||(s+=(Number(i.power_w)||0)*(r-t)/36e8)}return s}const Ge="#ff9800",Ke="#488fc2",qe="#8353d1",Ve="#f06292",Ye="#4db6ac",Ze="#5BC8D8",Xe="#8DC892",Je="#1F7A8C",Qe="#2E9E5B",ts="#E09A1A",es=a`
    :host { display: block; }
    ha-card { background: var(--card-background-color); border-radius: 16px; padding: 0; overflow: hidden; }
    .wrap { padding: 12px 14px 18px; display: grid; gap: 12px; }
    .head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
    .brand { display: flex; align-items: center; gap: 8px; font-weight: 800; font-size: 1rem; letter-spacing: -0.01em; }
    .brand ha-icon { color: #ff9800; --mdc-icon-size: 22px; }
    .pill { display: inline-flex; align-items: center; gap: 6px; font-size: 0.75rem; font-weight: 600;
            padding: 4px 10px; border-radius: 999px; border: 1px solid var(--divider-color);
            background: var(--secondary-background-color); }
    .pill i { width: 8px; height: 8px; border-radius: 50%; background: #2E9E5B; display: inline-block; }
    .pill.observe i { background: #E09A1A; }
    .lead { font-weight: 700; font-size: 1.2rem; line-height: 1.3; letter-spacing: -0.01em; }
    .lead small { display: block; font-weight: 500; font-size: 0.85rem; line-height: 1.4; color: var(--secondary-text-color); margin-top: 4px; }
    .sec { background: var(--secondary-background-color); border-radius: 14px; padding: 12px; display: grid; gap: 10px; min-width: 0; }
    .sec h3 { margin: 0; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--secondary-text-color); }
    .num { font-variant-numeric: tabular-nums; }
    .kv { display: grid; grid-template-columns: 1fr auto; gap: 6px 12px; font-size: 0.9rem; margin: 0; }
    .kv dt { color: var(--secondary-text-color); } .kv dd { margin: 0; text-align: right; font-weight: 600; }
    .src { display: inline-flex; align-items: center; gap: 6px; }
    .src i { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
    .tiles { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
    .tile { background: var(--card-background-color); border-radius: 12px; padding: 10px 12px; display: grid; gap: 2px; }
    .tile b { font-size: 1.25rem; font-weight: 800; letter-spacing: -0.02em; }
    .tile b small { font-size: 0.8rem; font-weight: 600; }
    .tile span { font-size: 0.75rem; color: var(--secondary-text-color); }
    .bar { height: 5px; border-radius: 3px; background: var(--divider-color); overflow: hidden; }
    .bar i { display: block; height: 100%; border-radius: 3px; }
    .why { display: grid; gap: 8px; }
    .why .row { display: grid; grid-template-columns: 28px 1fr; gap: 10px; align-items: start; }
    .why .dot { width: 28px; height: 28px; border-radius: 9px; display: grid; place-items: center; color: #fff; font-weight: 800; font-size: 0.75rem; }
    .why b { display: block; font-weight: 600; } .why span { color: var(--secondary-text-color); font-size: 0.85rem; }
    .list { display: grid; gap: 8px; }
    .item { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 12px; background: var(--card-background-color); }
    .item i { width: 10px; height: 10px; border-radius: 50%; background: #2E9E5B; }
    .item i.warn { background: #E09A1A; } .item i.off { background: var(--divider-color); } .item i.bad { background: #D64545; }
    .item span { font-size: 0.78rem; color: var(--secondary-text-color); display: block; }
    .btns { display: flex; flex-wrap: wrap; gap: 8px; }
    .btn { border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color);
           font: 600 0.85rem inherit; padding: 9px 14px; border-radius: 12px; cursor: pointer; min-height: 40px; }
    .btn.primary { background: #1F7A8C; color: #fff; border-color: transparent; }
    .btn[disabled] { opacity: 0.5; cursor: default; }
    .btn:focus-visible { outline: 2px solid #1F7A8C; outline-offset: 1px; }
    .hint { font-size: 0.78rem; color: var(--secondary-text-color); }
    .sub { display: inline-flex; gap: 4px; background: var(--card-background-color); border-radius: 10px; padding: 3px; }
    .sub button { border: 0; background: transparent; color: var(--secondary-text-color); font: 600 0.8rem inherit; padding: 6px 10px; border-radius: 8px; cursor: pointer; }
    .sub button[aria-pressed="true"] { background: var(--secondary-background-color); color: var(--primary-text-color); }
    select, input[type="time"], input[type="number"] { font: inherit; color: var(--primary-text-color); background: var(--card-background-color);
           border: 1px solid var(--divider-color); border-radius: 8px; padding: 4px 8px; max-width: 150px; }
    .toggle { display: inline-flex; align-items: center; gap: 8px; font-size: 0.85rem; }
    .toggle input { appearance: none; width: 40px; height: 24px; border-radius: 999px; background: var(--divider-color); position: relative; cursor: pointer; margin: 0; }
    .toggle input::after { content: ""; position: absolute; top: 3px; left: 3px; width: 18px; height: 18px; border-radius: 50%; background: var(--card-background-color); transition: left .15s; }
    .toggle input:checked { background: #1F7A8C; } .toggle input:checked::after { left: 19px; }
    .grid2 { display: grid; gap: 12px; }
    @media (min-width: 760px) { .grid2 { grid-template-columns: repeat(2, minmax(0, 1fr)); } .grid2 > .wide { grid-column: 1 / -1; } }
    @media (min-width: 1100px) { .grid2 { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
    :host(.observe) .sec { opacity: 0.85; }
    @media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
`;class ss extends Lt{constructor(){super(),this._prefix="sensor.sem_",this._key="",this._chargers=[]}setConfig(t){super.setConfig(t||{})}_watchIds(){return["switch.sem_observer_mode","sensor.sem_night_start_time","sensor.sem_night_end_time"]}set hass(t){if(this._hass=t,!t)return;const e=t.language,s="function"==typeof semLocalize;let i=!1;(e!==this._lang||s&&!this._localizeReady)&&(this._lang=e,this._localizeReady=s,i=!0),this._discover(t);const r=this._watchIds().map(e=>{const s=t.states[e];return s?s.state+"|"+(s.last_updated||""):""}).join("§")+"§"+this._chargers.join(",");(r!==this._key||i)&&(this._key=r,this.classList&&this.classList.toggle("observe",this._observer()),this._scheduleUpdate())}get hass(){return this._hass}_discover(t){const e=[];for(const s of Object.keys(t.states)){if(s.includes("_flow_"))continue;const t=s.match(/^sensor\.sem_charger_(.+)_power$/);t&&e.push(t[1])}e.sort(),this._chargers=e}_num(t){return At(this._hass?.states[t])}_str(t){const e=this._hass?.states[t];return e&&"unavailable"!==e.state&&"unknown"!==e.state?e.state:""}_attrs(t){return this._hass?.states[t]?.attributes||{}}_name(t){const e=this._hass?.states[t]?.attributes?.friendly_name;return e?String(e).replace(/^SEM\s+/i,""):t}_observer(){return"on"===this._str("switch.sem_observer_mode")}_clock(){const t=new Date;return String(t.getHours()).padStart(2,"0")+":"+String(t.getMinutes()).padStart(2,"0")}_night(){const t=this._str("sensor.sem_night_start_time"),e=this._str("sensor.sem_night_end_time");if(!t||!e)return!1;const s=this._clock();return t>e?s>=t||s<e:s>=t&&s<e}_chargerName(t){const e=this._hass?.states[`sensor.sem_charger_${t}_power`]?.attributes?.friendly_name||"",s=/^(?:SEM\s+)?(.*?)\s+Power$/i.exec(e);return s&&s[1]?s[1]:t.replace(/_/g," ")}_chargerEntity(t,e,s){const i=`${t}.sem_charger_${e}_${s}`;return this._hass?.states[i]?i:null}_powerW(t){const e=this._num(t);return null===e?null:"kw"===(this._unitOf(t)||"").toLowerCase()?1e3*e:e}_fmtKw(t,e=1){return null!==t&&Number.isFinite(t)?(t/1e3).toFixed(e):"—"}_fmt(t,e=1){return null!==t&&Number.isFinite(t)?Number(t).toFixed(e):"—"}_tf(t,e){return He(this._t(t),e,t=>this._t(t))}_currency(){const t=this._hass?.config?.currency;return t||"CHF"}_renderHead(){const t=this._observer();return H`
            <div class="head">
                <div class="brand"><ha-icon icon="mdi:white-balance-sunny"></ha-icon><span>SEM</span></div>
                <span class="pill ${t?"observe":""}"><i></i>${t?this._t("next_pill_observing"):this._t("next_pill_live")}</span>
            </div>`}_renderLead(t,e){return H`<div class="lead">${t}${e?H`<small>${e}</small>`:K}</div>`}getCardSize(){return 8}static getStubConfig(){return{}}}const is=["sensor.sem_solar_power","sensor.sem_grid_power","sensor.sem_battery_power","sensor.sem_battery_soc","sensor.sem_home_consumption_power","sensor.sem_ev_power","sensor.sem_charging_strategy","sensor.sem_battery_dynamic_floor_pct","number.sem_battery_buffer_soc","sensor.sem_consecutive_peak_15min","sensor.sem_target_peak_limit","sensor.sem_daily_solar_energy","sensor.sem_forecast_today_kwh","sensor.sem_daily_grid_import_energy","sensor.sem_daily_grid_export_energy","sensor.sem_daily_home_energy","sensor.sem_daily_ev_energy","sensor.sem_self_consumption_rate","sensor.sem_autarky_rate","sensor.sem_daily_co2_avoided","sensor.sem_daily_costs","sensor.sem_daily_savings","sensor.sem_monthly_costs","sensor.sem_monthly_savings","sensor.sem_tariff_current_import_rate","sensor.sem_tariff_current_export_rate","sensor.sem_tariff_price_level","sensor.sem_energy_plan","sensor.sem_forecast_tomorrow_kwh"];kt("sem-next-now-card",class extends ss{static get styles(){return es}_watchIds(){const t=[];for(const e of this._chargers)t.push(`sensor.sem_charger_${e}_power`,`sensor.sem_charger_${e}_commanded_current`,`sensor.sem_charger_${e}_daily_energy`,`number.sem_charger_${e}_daily_ev_target`,`time.sem_charger_${e}_target_time`,`sensor.sem_charger_${e}_vehicle_soc`,`number.sem_charger_${e}_target_soc`);return[...super._watchIds(),...is,...t]}_carFact(){for(const t of this._chargers){const e=this._powerW(`sensor.sem_charger_${t}_power`),s=this._num(`sensor.sem_charger_${t}_commanded_current`),i=this._remainingKwh(t);if(null!==e&&(e>50||null!==i&&i>.1))return{present:!0,charging:e>50,powerW:e,amps:s,remainingKwh:i,targetTime:(this._str(`time.sem_charger_${t}_target_time`)||"").slice(0,5),cid:t}}return null}_remainingKwh(t){if("soc"===(this._str(`select.sem_charger_${t}_ev_target_type`)||"kwh")){const e=this._num(`sensor.sem_charger_${t}_vehicle_soc`),s=this._num(`number.sem_charger_${t}_target_soc`),i=this._num(`number.sem_charger_${t}_ev_battery_capacity_kwh`);return null===e||null===s||null===i?null:Math.max(0,(s-e)/100*i)}const e=this._num(`number.sem_charger_${t}_daily_ev_target`),s=this._num(`sensor.sem_charger_${t}_daily_energy`);return null===e||null===s?null:Math.max(0,e-s)}_lead(){const t=this._num("sensor.sem_battery_soc"),e=function(t){const e=t.car||null,s=t.battery||null,i=Number.isFinite(t.gridW)&&t.gridW<-100,r=Number.isFinite(t.gridW)&&t.gridW>Pe,a=Number.isFinite(t.solarW)&&t.solarW>100,n=Number.isFinite(t.batteryW)&&t.batteryW<-100,o=n?"next_src_battery":i?"next_src_grid":"next_src_sun",l=t.observer?"next_lead_observing":t.night?"next_lead_night":"next_lead_day";let c;Number.isFinite(t.solarW)||Number.isFinite(t.gridW)||Number.isFinite(t.batteryW)||e&&e.present?e&&e.present&&e.charging?t.night||!a?(c={key:"next_lead_car_grid",params:{amps:We(e.amps),kwh:Ue(e.remainingKwh),time:e.targetTime||""}},Number.isFinite(e.remainingKwh)||(c={key:"next_lead_car_charging",params:{kw:Ue(e.powerW/1e3)}})):c={key:"next_lead_car_sun",params:{kw:Ue(e.powerW/1e3)}}:c=e&&e.present&&Number.isFinite(e.remainingKwh)&&e.remainingKwh>.1?{key:"next_lead_car_waits",params:{kwh:Ue(e.remainingKwh),time:e.targetTime||""}}:a&&r?{key:"next_lead_sun_export",params:{kw:Ue(t.gridW/1e3)}}:a&&s&&Number.isFinite(t.batteryW)&&t.batteryW>Pe?{key:"next_lead_sun_battery",params:{soc:We(s.soc)}}:a?{key:"next_lead_sun_house",params:{}}:{key:"next_lead_house_on",params:{source:o}}:c={key:"next_lead_unknown",params:{}};let d=null;return s&&Number.isFinite(s.soc)&&(d=Number.isFinite(s.floorPct)&&s.soc<s.floorPct&&!n?{key:"next_sub_battery_rests",params:{soc:We(s.soc),floor:We(s.floorPct)}}:n?{key:"next_sub_battery_house",params:{soc:We(s.soc)}}:{key:"next_sub_battery_at",params:{soc:We(s.soc)}}),t.night&&t.sunAt?d=d?{key:"next_sub_two",params:{a:d,b:{key:"next_sub_sun_at",params:{time:t.sunAt}}}}:{key:"next_sub_sun_at",params:{time:t.sunAt}}:!t.night&&t.nightStart&&(d=d?{key:"next_sub_two",params:{a:d,b:{key:"next_sub_night_at",params:{time:t.nightStart}}}}:{key:"next_sub_night_at",params:{time:t.nightStart}}),{prefix:l,main:c,sub:d}}({night:this._night(),observer:this._observer(),solarW:this._powerW("sensor.sem_solar_power"),gridW:this._powerW("sensor.sem_grid_power"),batteryW:this._powerW("sensor.sem_battery_power"),car:this._carFact(),battery:null===t?null:{soc:t,floorPct:this._num("sensor.sem_battery_dynamic_floor_pct"),bufferPct:this._num("number.sem_battery_buffer_soc")},sunAt:this._str("sensor.sem_night_end_time"),nightStart:this._str("sensor.sem_night_start_time")});return{main:this._t(e.prefix)+" "+this._tf(e.main.key,e.main.params),sub:e.sub?this._tf(e.sub.key,e.sub.params):""}}_flow(){const t=this._powerW("sensor.sem_solar_power"),e=this._powerW("sensor.sem_grid_power"),s=this._powerW("sensor.sem_battery_power"),i=this._powerW("sensor.sem_home_consumption_power"),r=this._powerW("sensor.sem_ev_power"),a=t??0,n=e??0,o=s??0,l=r??0,c=this._num("sensor.sem_battery_soc"),d=(t,e,s,i,r,a)=>j`
            <circle cx="${t}" cy="${e}" r="26" fill="var(--card-background-color)" stroke="${r}" stroke-width="2.5" opacity="${a?.45:1}"></circle>
            <text x="${t}" y="${e-4}" text-anchor="middle" font-size="11" font-weight="600" fill="var(--primary-text-color)">${s}</text>
            <text x="${t}" y="${e+11}" text-anchor="middle" font-size="11" fill="var(--secondary-text-color)">${i}</text>`,p=(t,e,s)=>s?j`<path d="${t}" fill="none" stroke="${e}" stroke-width="3" stroke-linecap="round" marker-end="url(#nxarr)"></path>`:K,_=t=>null===t?"—":`${(Math.abs(t)/1e3).toFixed(1)} kW`;return H`
            <svg viewBox="0 0 360 170" width="100%" role="img" aria-label="${this._t("next_power_now")}">
                <defs><marker id="nxarr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="context-stroke"></path></marker></defs>
                ${d(60,40,this._t("next_src_solar"),_(t),Ge,a<50)}
                ${d(60,130,this._t("next_src_grid"),_(e),Ke,Math.abs(n)<50)}
                ${d(180,85,this._t("next_src_house"),_(i),Ze,null===i)}
                ${d(300,40,this._t("next_src_battery"),null===c?_(s):`${Math.round(c)} %`,Ye,Math.abs(o)<50)}
                ${d(300,130,this._t("next_src_car"),_(r),Xe,l<50)}
                ${p("M88 48 C120 60 130 70 148 78",Ge,a>50)}
                ${p("M88 122 C120 110 130 100 148 93",Ke,n<-50)}
                ${p("M148 93 C130 100 120 110 88 122",qe,n>50)}
                ${p("M212 78 C240 70 250 60 272 48",Ve,o>50)}
                ${p("M272 48 C250 60 240 70 212 78",Ye,o<-50)}
                ${p("M212 95 C240 105 250 118 272 126",Xe,l>50)}
            </svg>`}_why(){const t=[],e=this._hass?.states["sensor.sem_charging_strategy"];if(e&&e.state&&"unavailable"!==e.state){const s=String(e.attributes?.reason||e.state),[i,...r]=s.split(/\s[—–-]\s|\[/);t.push({dot:"EV",color:Xe,title:i.trim(),text:r.join(" ").replace(/\]$/,"").trim()})}const s=this._num("sensor.sem_battery_soc"),i=this._num("sensor.sem_battery_dynamic_floor_pct"),r=this._powerW("sensor.sem_battery_power");if(null!==s){const e=null!==r&&r<-50?this._t("next_why_batt_house"):null!==r&&r>50?this._t("next_why_batt_charging"):this._t("next_why_batt_rest"),a=null!==i&&s<i?this._tf("next_why_batt_floor",{soc:Math.round(s),floor:Math.round(i)}):this._tf("next_sub_battery_at",{soc:Math.round(s)});t.push({dot:"B",color:Ye,title:e,text:a})}const a=this._num("sensor.sem_consecutive_peak_15min"),n=this._num("sensor.sem_target_peak_limit"),o=this._powerW("sensor.sem_grid_power");return null!==o&&null!==a&&t.push({dot:"G",color:Ke,title:o<-50?this._tf("next_why_import",{kw:this._fmtKw(-o)}):o>50?this._tf("next_why_export",{kw:this._fmtKw(o)}):this._t("next_why_grid_quiet"),text:null!==n?this._tf("next_why_peak",{kw:this._fmt(a,1),limit:this._fmt(n,1)}):this._tf("next_why_peak_nolimit",{kw:this._fmt(a,1)})}),t.length?H`<div class="sec"><h3>${this._t("next_why")}</h3><div class="why">
            ${t.map(t=>H`<div class="row"><div class="dot" style="background:${t.color}">${t.dot}</div><div><b>${t.title}</b><span>${t.text}</span></div></div>`)}
        </div></div>`:K}_today(){const t=this._num("sensor.sem_daily_solar_energy"),e=this._num("sensor.sem_forecast_today_kwh"),s=this._num("sensor.sem_daily_grid_import_energy"),i=this._num("sensor.sem_daily_grid_export_energy"),r=this._num("sensor.sem_daily_home_energy"),a=this._num("sensor.sem_daily_ev_energy"),n=Math.max(1,...[t,s,r,a].filter(t=>null!==t)),o=(t,e,s,i)=>null===t?K:H`
            <div class="tile"><b class="num">${this._fmt(t,1)} <small>kWh</small></b>
                <span class="src"><i style="background:${s}"></i>${e}${i?" · "+i:""}</span>
                <div class="bar"><i style="width:${Math.min(100,t/n*100)}%;background:${s}"></i></div></div>`,l=e&&null!==t&&e>0?this._tf("next_pct_forecast",{pct:Math.round(t/e*100)}):"",c=this._num("sensor.sem_self_consumption_rate"),d=this._num("sensor.sem_autarky_rate"),p=this._num("sensor.sem_daily_co2_avoided");return H`<div class="sec"><h3>${this._t("next_today")}</h3>
            <div class="tiles">
                ${o(t,this._t("next_src_solar"),Ge,l)}
                ${o(s,this._t("next_grid_in"),Ke,null!==i?`${this._fmt(i,1)} ${this._t("next_out")}`:"")}
                ${o(r,this._t("next_src_house"),Ze,"")}
                ${o(a,this._t("next_src_car"),Xe,"")}
            </div>
            <dl class="kv">
                ${null!==c?H`<dt>${this._t("next_self_use")}</dt><dd class="num">${this._fmt(c,0)} %</dd>`:K}
                ${null!==d?H`<dt>${this._t("next_own_supply")}</dt><dd class="num">${this._fmt(d,0)} %</dd>`:K}
                ${null!==p?H`<dt>${this._t("next_co2_avoided")}</dt><dd class="num">${this._fmt(p,1)} ${this._kgUnit("daily_co2_avoided")}</dd>`:K}
            </dl></div>`}_money(){const t=this._currency(),e=this._num("sensor.sem_daily_costs"),s=this._num("sensor.sem_daily_savings"),i=this._num("sensor.sem_monthly_costs"),r=this._num("sensor.sem_monthly_savings"),a=this._num("sensor.sem_tariff_current_import_rate"),n=this._num("sensor.sem_tariff_current_export_rate"),o=this._str("sensor.sem_tariff_price_level");return null===e&&null===a?K:H`<div class="sec"><h3>${this._t("next_money")}</h3><dl class="kv">
            ${null!==e?H`<dt>${this._t("next_today")}</dt><dd class="num">${this._fmt(e,2)} ${t}</dd>`:K}
            ${null!==s?H`<dt>${this._t("next_saved")}</dt><dd class="num" style="color:${Qe}">${this._fmt(s,2)} ${t}</dd>`:K}
            ${null!==a?H`<dt>${this._t("next_price")}</dt><dd class="num">${"flat"!==o&&o?"":this._t("next_one_rate")+" · "}${this._fmt(a,2)}${null!==n?" / "+this._fmt(n,3):""}</dd>`:K}
            ${null!==i?H`<dt>${this._t("next_this_month")}</dt><dd class="num">${this._fmt(i,2)} ${t}${null!==r?" · "+this._t("next_saved").toLowerCase()+" "+this._fmt(r,2):""}</dd>`:K}
        </dl></div>`}_next(){const t=[],e=this._attrs("sensor.sem_energy_plan"),s=Date.now(),i=(Array.isArray(e.blocks)?e.blocks:[]).filter(t=>Date.parse(t.start)>s).sort((t,e)=>Date.parse(t.start)-Date.parse(e.start));if(i.length){const e=i[0],s=new Date(Date.parse(e.start)),r=String(e.id).startsWith("ev:")?this._t("next_src_car"):String(e.id).startsWith("battery")?this._t("next_src_battery"):String(e.id).replace(/^load:/,"");t.push({cls:"",title:this._tf("next_next_block",{who:r}),sub:`${this._fmtKw(e.power_w)} kW`,at:this._hhmm(s)})}const r=this._num("sensor.sem_forecast_tomorrow_kwh"),a=this._str("sensor.sem_night_end_time");null!==r&&t.push({cls:"off",title:this._t("next_sun_tomorrow"),sub:this._tf("next_kwh_expected",{kwh:this._fmt(r,1)}),at:a});const n=this._str("sensor.sem_night_start_time");return n&&t.push({cls:"off",title:this._t("next_night_starts"),sub:this._t("next_night_starts_sub"),at:n}),t.length?H`<div class="sec"><h3>${this._t("next_next")}</h3><div class="list">
            ${t.map(t=>H`<div class="item"><i class="${t.cls}"></i><div>${t.title}<span>${t.sub}</span></div><b class="num">${t.at}</b></div>`)}
        </div></div>`:K}_hhmm(t){return String(t.getHours()).padStart(2,"0")+":"+String(t.getMinutes()).padStart(2,"0")}render(){if(!this._hass)return K;const t=this._lead();return H`<ha-card><div class="wrap">
            ${this._renderHead()}
            ${this._renderLead(t.main,t.sub)}
            <div class="grid2">
                <div class="sec wide"><h3>${this._t("next_power_now")}</h3>${this._flow()}</div>
                ${this._why()}
                ${this._today()}
                ${this._money()}
                ${this._next()}
            </div>
        </div></ha-card>`}},{type:"sem-next-now-card",name:"SEM Next · Now",description:"What SEM does right now and why: power flow, reasons, today, money, next",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-next-now-card",preview:!0});const rs="#8353d1",as="#488fc2",ns="#f06292",os="#4db6ac",ls="#8DC892",cs="#5BC8D8",ds=36e5;function ps(t,e){const s=/^(\d{1,2}):(\d{2})/.exec(String(t||""));if(!s)return null;const i=new Date(e.getTime());return i.setHours(Number(s[1]),Number(s[2]),0,0),i.getTime()<=e.getTime()&&i.setDate(i.getDate()+1),i}function _s(t,e,s){return Math.min(1,Math.max(0,(t-e)/s))}const hs=["sensor.sem_energy_plan","sensor.sem_forecast_tomorrow_kwh","sensor.sem_forecast_today_kwh","sensor.sem_tariff_price_level","sensor.sem_controllable_devices_count","switch.sem_energy_plan_actuation"],us=30,gs=24;kt("sem-next-plan-card",class extends ss{static get properties(){return{_picked:{state:!0},_confirm:{state:!0}}}static get styles(){return es}constructor(){super(),this._picked=null,this._confirm=null,this._savedMode={}}_watchIds(){const t=this._chargers.map(t=>`select.sem_charger_${t}_charge_mode`);return[...super._watchIds(),...hs,...t]}_loads(){const t=this._attrs("sensor.sem_controllable_devices_count").devices||{};return Object.entries(t).map(([t,e])=>({id:t,name:e?.name||t}))}_model(){return function(t){const e=t.now instanceof Date?t.now:new Date(t.now||Date.now()),s=t.hours||24,i=e.getTime(),r=s*ds,a=i+r,n=t.plan&&"object"==typeof t.plan?t.plan:{},o=(t,e)=>{const s=Math.max(t,i),n=Math.min(e,a);return n>s?[_s(s,i,r),_s(n,i,r)]:null},l=[],c=new Date(i);c.setMinutes(0,0,0);for(let t=c.getTime()+ds;t<=a;t+=ds){const e=new Date(t);e.getHours()%3==0&&l.push({x:_s(t,i,r),label:String(e.getHours()).padStart(2,"0")+":00"})}let d=null;const p=ps(t.nightEnd,e),_=ps(t.nightStart,e);if(p&&_){let e=p.getTime(),s=_.getTime();s<e&&(e=i);const r=o(e,s);r&&(d={x0:r[0],x1:r[1],kwh:s<p.getTime()?t.forecastTodayKwh:t.forecastTomorrowKwh})}let h=null;const u=Array.isArray(n.slots)?n.slots:[],g=u.map(t=>t.price).filter(t=>Number.isFinite(Number(t)));if(g.length&&new Set(g.map(t=>Number(t).toFixed(4))).size>1){h=[];for(const t of u){const e=o(Date.parse(t.start),Date.parse(t.end));e&&Number.isFinite(Number(t.price))&&h.push({x0:e[0],x1:e[1],price:Number(t.price),cheap:!!t.cheap})}}const m=[],f={id:"grid",labelKey:"next_lane_grid",color:as,blocks:[]},y=n.takeover?Date.parse(n.takeover):NaN;if(Number.isFinite(y)&&p){const t=o(y,p.getTime());t&&f.blocks.push({x0:t[0],x1:t[1],kind:"grid",dashed:!0,reasonKey:"next_reason_takeover",params:{}})}m.push(f);const v={id:"battery",labelKey:"next_lane_battery",color:os,blocks:[]};for(const t of Array.isArray(n.blocks)?n.blocks:[]){if(!String(t.id).startsWith("battery"))continue;const e=o(Date.parse(t.start),Date.parse(t.end));e&&v.blocks.push({x0:e[0],x1:e[1],kind:"battery_in",color:ns,dashed:!0,powerW:Number(t.power_w)||0,reasonKey:"next_reason_battery_charge",params:{kw:((Number(t.power_w)||0)/1e3).toFixed(1)}})}for(const t of Array.isArray(n.batt_runs)?n.batt_runs:[]){const e=o(Date.parse(t.start),Date.parse(t.end));e&&v.blocks.push({x0:e[0],x1:e[1],kind:"battery_out",color:os,dashed:!0,reasonKey:"next_reason_battery_house",params:{}})}m.push(v);const b=Array.isArray(n.demands)?n.demands:[],x=t=>b.find(e=>e.id===t)||{},$=(t,e,s,r)=>{for(const a of e||[]){const e={id:`${t}:${a.id}`,labelKey:s,label:a.name||a.id,color:r,blocks:[]};for(const s of Array.isArray(n.blocks)?n.blocks:[]){if(s.id!==e.id)continue;const a=o(Date.parse(s.start),Date.parse(s.end));if(!a)continue;const n=x(s.id);e.blocks.push({x0:a[0],x1:a[1],kind:t,color:r,dashed:Date.parse(s.start)>i,powerW:Number(s.power_w)||0,reasonKey:"ev"===t?"next_reason_ev_block":"next_reason_load_block",params:{kw:((Number(s.power_w)||0)/1e3).toFixed(1),status:n.status||"",note:n.note||""}})}m.push(e)}};$("ev",t.chargers,"next_lane_car",ls),$("load",t.loads,"next_lane_load",cs);const w=Array.isArray(n.not_scheduled)?n.not_scheduled:[];return{start:i,end:a,hours:s,ticks:l,sun:d,price:h,lanes:m,notScheduled:w,why:n.why||"",fits:n.fits,cost:n.total_cost,computedAt:n.computed_at||""}}({now:new Date,plan:this._attrs("sensor.sem_energy_plan"),chargers:this._chargers.map(t=>({id:t,name:this._chargerName(t)})),loads:this._loads(),nightStart:this._str("sensor.sem_night_start_time"),nightEnd:this._str("sensor.sem_night_end_time"),forecastTomorrowKwh:this._num("sensor.sem_forecast_tomorrow_kwh"),forecastTodayKwh:this._num("sensor.sem_forecast_today_kwh")})}_timeline(t){const e=t.lanes,s=1+(t.price?1:0)+e.length,i=gs+s*us+20,r=t=>54+658*t;let a=0;const n=[],o=(t,e)=>j`<text x="4" y="${gs+e*us+19.2}" font-size="11" font-weight="600" fill="var(--secondary-text-color)">${t}</text>
            <line x1="${54}" y1="${gs+(e+1)*us}" x2="${712}" y2="${gs+(e+1)*us}" stroke="var(--divider-color)"></line>`;if(n.push(o(this._t("next_lane_sun"),a)),t.sun){const e=[];for(let s=0;s<=24;s++){const i=s/24,n=t.sun.x0+(t.sun.x1-t.sun.x0)*i,o=gs+a*us+27-Math.sin(Math.PI*i)*us*.78;e.push(`${r(n).toFixed(1)},${o.toFixed(1)}`)}n.push(j`<polygon points="${r(t.sun.x0)},${gs+a*us+27} ${e.join(" ")} ${r(t.sun.x1)},${gs+a*us+27}" fill="${Ge}" opacity="0.35" stroke="${Ge}" stroke-width="1.5" stroke-dasharray="4 3"></polygon>`),Number.isFinite(t.sun.kwh)&&n.push(j`<text x="${r((t.sun.x0+t.sun.x1)/2)}" y="${gs+a*us+13.5}" font-size="10" font-weight="600" text-anchor="middle" fill="var(--primary-text-color)">${this._fmt(t.sun.kwh,1)} kWh</text>`)}if(a++,t.price){n.push(o(this._t("next_lane_price"),a));const e=Math.max(...t.price.map(t=>t.price),.01);for(const s of t.price){const t=Math.max(3,s.price/e*22);n.push(j`<rect x="${r(s.x0)+.5}" y="${gs+a*us+us-4-t}" width="${Math.max(1,r(s.x1)-r(s.x0)-1)}" height="${t}" fill="${s.cheap?Qe:rs}" opacity="0.8"></rect>`)}a++}e.forEach((t,e)=>{n.push(o(t.label||this._t(t.labelKey),a)),t.blocks.forEach((s,i)=>{const o=`${e}:${i}`,l=this._picked===o;n.push(j`<rect x="${r(s.x0)+1}" y="${gs+a*us+5}" width="${Math.max(2,r(s.x1)-r(s.x0)-2)}" height="${20}" rx="6"
                    fill="${s.color||t.color}" opacity="${this._picked&&!l?.5:.9}"
                    stroke="${s.dashed?"var(--primary-text-color)":"none"}" stroke-width="1" stroke-dasharray="${s.dashed?"3 3":""}"
                    style="cursor:pointer" @click=${()=>this._pick(o,t,s)}></rect>`)}),a++});const l=t.ticks.map(t=>j`<line x1="${r(t.x)}" y1="${18}" x2="${r(t.x)}" y2="${gs+s*us}" stroke="var(--divider-color)"></line>
            <text x="${r(t.x)}" y="${gs+s*us+14}" font-size="10" text-anchor="middle" fill="var(--secondary-text-color)">${t.label}</text>`);return H`<svg viewBox="0 0 ${720} ${i}" width="100%" role="img" aria-label="${this._t("next_timeline")}">
            ${l}${n}
            <line x1="${r(0)}" y1="${14}" x2="${r(0)}" y2="${gs+s*us}" stroke="${Je}" stroke-width="2"></line>
            <text x="${r(0)+4}" y="${12}" font-size="10" font-weight="700" fill="${Je}">${this._t("next_now_marker")}</text>
        </svg>`}_pick(t,e,s){this._picked=this._picked===t?null:t,this._pickedText=this._picked?{title:`${e.label||this._t(e.labelKey)} · ${this._span(s)}`,text:this._tf(s.reasonKey,s.params)}:null}_span(t){const e=this._m;if(!e)return"";const s=t=>{const s=new Date(e.start+t*(e.end-e.start));return String(s.getHours()).padStart(2,"0")+":"+String(s.getMinutes()).padStart(2,"0")};return`${s(t.x0)} → ${s(t.x1)}`}_why(t){const e=[],s=this._attrs("sensor.sem_energy_plan");t.why&&e.push({dot:"P",color:Je,title:this._t("next_plan_says"),text:String(t.why)});for(const t of Array.isArray(s.demands)?s.demands:[]){const s=String(t.id).startsWith("ev:"),i=s?this._chargerName(String(t.id).slice(3)):String(t.id).replace(/^(load|battery):?/,"")||this._t("next_src_battery");e.push({dot:s?"EV":String(t.id).startsWith("battery")?"B":"L",color:s?Xe:String(t.id).startsWith("battery")?Ve:Ze,title:`${i}: ${this._t("next_status_"+(t.status||"fits"))}`,text:t.note||""})}for(const s of t.notScheduled)e.push({dot:"!",color:ts,title:this._t("next_not_scheduled"),text:"string"==typeof s?s:(s?.id||"")+" "+(s?.reason||s?.note||"")});return e.length?H`<div class="sec"><h3>${this._t("next_why_plan")}</h3><div class="why">
            ${e.map(t=>H`<div class="row"><div class="dot" style="background:${t.color}">${t.dot}</div><div><b>${t.title}</b>${t.text?H`<span>${t.text}</span>`:K}</div></div>`)}
        </div></div>`:K}_expected(t){const e=this._attrs("sensor.sem_energy_plan"),s=je(e.blocks,t=>!String(t).startsWith("battery_out")),i=this._currency(),r=this._num("sensor.sem_forecast_tomorrow_kwh");return H`<div class="sec"><h3>${this._t("next_expected")}</h3><dl class="kv">
            ${e.blocks?H`<dt>${this._t("next_grid_planned")}</dt><dd class="num">${this._fmt(s,1)} kWh${Number.isFinite(Number(t.cost))?` · ${this._fmt(Number(t.cost),2)} ${i}`:""}</dd>`:K}
            ${null!==r?H`<dt>${this._t("next_sun_tomorrow")}</dt><dd class="num">${this._fmt(r,1)} kWh</dd>`:K}
            ${t.computedAt?H`<dt>${this._t("next_plan_made")}</dt><dd class="num">${this._stamp(t.computedAt)}</dd>`:K}
            ${void 0!==t.fits?H`<dt>${this._t("next_plan_fits")}</dt><dd>${t.fits?this._t("next_yes"):this._t("next_no")}</dd>`:K}
        </dl></div>`}_stamp(t){const e=Date.parse(t);if(!Number.isFinite(e))return String(t);const s=new Date(e);return String(s.getHours()).padStart(2,"0")+":"+String(s.getMinutes()).padStart(2,"0")}_change(){if(!this._chargers.length)return K;const t=this._observer();return H`<div class="sec"><h3>${this._t("next_change_now")}</h3>
            ${this._chargers.map(e=>{const s=`select.sem_charger_${e}_charge_mode`,i=this._str(s);if(!i)return K;const r="always_max"===i,a=this._confirm===e;return H`<div class="item"><i class="${r?"warn":""}"></i>
                    <div>${this._chargerName(e)}<span>${this._t("next_mode")}: ${this._t("charge_mode_"+i)||i}</span></div>
                    <div class="btns">
                        ${a?H`
                            <button class="btn primary" ?disabled=${t} @click=${()=>this._chargeNow(e,s,i)}>${this._t("next_confirm")}</button>
                            <button class="btn" @click=${()=>{this._confirm=null}}>${this._t("next_cancel")}</button>`:r&&this._savedMode[e]?H`<button class="btn" ?disabled=${t} @click=${()=>this._backToPlan(e,s)}>${this._t("next_back_to_plan")}</button>`:H`<button class="btn primary" ?disabled=${t||r} @click=${()=>{this._confirm=e}}>${this._t("next_charge_now")}</button>`}
                    </div></div>`})}
            <div class="hint">${t?this._t("next_observing_hint"):this._t("next_change_hint")}</div>
        </div>`}async _chargeNow(t,e,s){this._savedMode={...this._savedMode,[t]:s},this._confirm=null,await this._hass.callService("select","select_option",{entity_id:e,option:"always_max"})}async _backToPlan(t,e){const s=this._savedMode[t];if(!s)return;await this._hass.callService("select","select_option",{entity_id:e,option:s});const{[t]:i,...r}=this._savedMode;this._savedMode=r,this.requestUpdate()}render(){if(!this._hass)return K;const t=this._model();this._m=t;const e=function(t,e){if(!t||"object"!=typeof t||!Array.isArray(t.blocks)||!t.computed_at)return{main:{key:"next_plan_none",params:{}},sub:null};const s=je(t.blocks,t=>String(t).startsWith("ev:")),i=je(t.blocks,t=>String(t).startsWith("load:"));return{main:s>.05?{key:"next_plan_car",params:{kwh:Ue(s)}}:i>.05?{key:"next_plan_loads",params:{kwh:Ue(i)}}:{key:"next_plan_quiet",params:{}},sub:{key:"next_plan_sub",params:{time:e?.computedAt||"",cost:e?.cost||"",fits:e?.fitsKey||"",sun:Ue(e?.sunTomorrowKwh)}}}}(this._attrs("sensor.sem_energy_plan"),{computedAt:t.computedAt?this._stamp(t.computedAt):"",cost:Number.isFinite(Number(t.cost))?`${this._fmt(Number(t.cost),2)} ${this._currency()}`:"",fitsKey:void 0===t.fits?"":this._t(t.fits?"next_fits_yes":"next_fits_no"),sunTomorrowKwh:this._num("sensor.sem_forecast_tomorrow_kwh")}),s="flat"===(this._str("sensor.sem_tariff_price_level")||"flat"),i=this._tf(e.main.key,e.main.params),r=e.sub?this._tf(e.sub.key,e.sub.params)+(s?" "+this._t("next_one_rate_sub"):""):"";return H`<ha-card><div class="wrap">
            ${this._renderHead()}
            ${this._renderLead(i,r)}
            <div class="grid2">
                <div class="sec wide"><h3>${this._t("next_timeline")}</h3>
                    ${t.computedAt?this._timeline(t):H`<div class="hint">${this._t("next_plan_none")}</div>`}
                    <div class="hint" style="display:flex;flex-wrap:wrap;gap:10px 14px">
                        <span class="src"><i style="background:${Ge}"></i>${this._t("next_lane_sun")}</span>
                        <span class="src"><i style="background:${Ke}"></i>${this._t("next_lane_grid")}</span>
                        <span class="src"><i style="background:${Ve}"></i>${this._t("next_battery_charging")}</span>
                        <span class="src"><i style="background:${Ye}"></i>${this._t("next_battery_to_house")}</span>
                        <span class="src"><i style="background:${Xe}"></i>${this._t("next_src_car")}</span>
                        <span class="src"><i style="background:${Ze}"></i>${this._t("next_lane_load")}</span>
                    </div>
                    <div class="tile">${this._pickedText?H`<b style="font-size:0.95rem">${this._pickedText.title}</b><span>${this._pickedText.text}</span>`:H`<b style="font-size:0.95rem">${this._t("next_tap_block")}</b><span>${this._t("next_tap_block_sub")}</span>`}</div>
                    <div class="hint">${this._t("next_dashed_hint")}</div>
                </div>
                ${this._why(t)}
                ${this._expected(t)}
                ${this._change()}
            </div>
        </div></ha-card>`}},{type:"sem-next-plan-card",name:"SEM Next · Plan",description:"The next 24 hours as one timeline, why this plan, and one change you can make now",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-next-plan-card",preview:!0});const ms=["sensor.sem_battery_soc","sensor.sem_battery_power","sensor.sem_battery_dynamic_floor_pct","sensor.sem_battery_spendable_kwh","number.sem_battery_buffer_soc","number.sem_battery_priority_soc","select.sem_battery_mode","switch.sem_battery_may_assist_ev","sensor.sem_daily_battery_charge_energy","sensor.sem_daily_battery_discharge_energy","sensor.sem_controllable_devices_count","sensor.sem_energy_plan"],fs=["power","commanded_current","daily_energy","session_energy","session_solar_share","vehicle_soc","charge_mode","daily_ev_target","daily_ev_target_max","target_soc","target_soc_max","ev_target_type","target_time","pause_charging","minimum_current","maximum_current"];function ys(t,e,s){const i=atob(e||""),r=new Uint8Array(i.length);for(let t=0;t<i.length;t++)r[t]=i.charCodeAt(t);const a=new Blob([r],{type:s}),n=URL.createObjectURL(a),o=document.createElement("a");return o.href=n,o.download=t,document.body.appendChild(o),o.click(),o.remove(),setTimeout(()=>URL.revokeObjectURL(n),1e3),a}kt("sem-next-devices-card",class extends ss{static get styles(){return es}_watchIds(){const t=[];for(const e of this._chargers)for(const s of["sensor","number","select","time","switch"])for(const i of fs){const r=`${s}.sem_charger_${e}_${i}`;this._hass?.states[r]&&t.push(r)}const e=this._attrs("sensor.sem_controllable_devices_count").devices||{};for(const s of Object.values(e))s?.power_entity&&t.push(s.power_entity),s?.switch_entity&&t.push(s.switch_entity);return[...super._watchIds(),...ms,...t]}_nextBlock(t){const e=this._attrs("sensor.sem_energy_plan"),s=Date.now(),i=(Array.isArray(e.blocks)?e.blocks:[]).filter(e=>String(e.id)===t&&Date.parse(e.end)>s).sort((t,e)=>Date.parse(t.start)-Date.parse(e.start))[0];if(!i)return"";const r=new Date(Math.max(s,Date.parse(i.start))),a=new Date(Date.parse(i.end)),n=t=>String(t.getHours()).padStart(2,"0")+":"+String(t.getMinutes()).padStart(2,"0");return`${n(r)} → ${n(a)} · ${this._fmtKw(i.power_w)} kW`}_charger(t){const e=(e,s)=>this._chargerEntity(e,t,s),s=this._powerW(`sensor.sem_charger_${t}_power`),i=this._num(`sensor.sem_charger_${t}_commanded_current`),r=this._num(`sensor.sem_charger_${t}_daily_energy`),a=this._num(`sensor.sem_charger_${t}_session_energy`),n=this._num(`sensor.sem_charger_${t}_session_solar_share`),o=this._num(`sensor.sem_charger_${t}_vehicle_soc`),l=e("select","charge_mode"),c=l?this._str(l):"",d=e("select","ev_target_type"),p=d?this._str(d):"kwh",_=e("number","soc"===p?"target_soc":"daily_ev_target"),h=e("number","soc"===p?"target_soc_max":"daily_ev_target_max"),u=e("time","target_time"),g=e("switch","pause_charging"),m="soc"===p?"%":"kWh",f=null!==s&&s>50?this._tf("next_dev_charging",{kw:this._fmtKw(s),amps:null===i?"—":Math.round(i)}):g&&"on"===this._str(g)?this._t("next_dev_paused"):this._t("next_dev_idle"),y=this._observer();return H`<div class="sec">
            <h3><span class="src"><i style="background:${Xe}"></i>${this._chargerName(t)}</span></h3>
            <div class="lead" style="font-size:1rem">${f}
                <small>${null!==r?this._tf("next_dev_today_kwh",{kwh:this._fmt(r,1)}):""}${null!==a?` · ${this._t("next_session")} ${this._fmt(a,1)} kWh`:""}${null!==n?` · ${this._fmt(n,0)} % ${this._t("next_from_sun")}`:""}${null!==o?` · ${this._t("next_car_soc")} ${this._fmt(o,0)} %`:""}</small>
            </div>
            <dl class="kv">
                ${l?H`<dt>${this._t("next_mode")}</dt><dd>
                    <select ?disabled=${y} @change=${t=>this._selectOption(l,t.target.value)}>
                        ${(this._attrs(l).options||[]).map(t=>H`<option value="${t}" ?selected=${t===c}>${this._t("charge_mode_"+t)||t}</option>`)}
                    </select></dd>`:K}
                ${_?H`<dt>${this._t("next_at_least")}</dt><dd><input type="number" ?disabled=${y} .value=${String(this._num(_)??"")} min="${this._attrs(_).min??0}" max="${this._attrs(_).max??200}" step="${this._attrs(_).step??.5}" @change=${t=>this._setNumber(_,Number(t.target.value))}> ${m}</dd>`:K}
                ${h?H`<dt>${this._t("next_up_to")}</dt><dd><input type="number" ?disabled=${y} .value=${String(this._num(h)??"")} min="${this._attrs(h).min??0}" max="${this._attrs(h).max??200}" step="${this._attrs(h).step??.5}" @change=${t=>this._setNumber(h,Number(t.target.value))}> ${m}</dd>`:K}
                ${u?H`<dt>${this._t("next_charge_by")}</dt><dd><input type="time" ?disabled=${y} .value=${(this._str(u)||"").slice(0,5)} @change=${t=>this._setTime(u,t.target.value)}></dd>`:K}
                <dt>${this._t("next_next")}</dt><dd>${this._nextBlock(`ev:${t}`)||this._t("next_nothing_planned")}</dd>
            </dl>
            ${g?H`<label class="toggle"><input type="checkbox" ?disabled=${y} .checked=${"on"===this._str(g)} @change=${()=>this._toggleSwitch(g)}> ${this._t("next_pause")}</label>`:K}
        </div>`}async _setTime(t,e){e&&await this._hass.callService("time","set_value",{entity_id:t,time:5===e.length?e+":00":e})}_battery(){const t=this._num("sensor.sem_battery_soc");if(null===t)return K;const e=this._powerW("sensor.sem_battery_power"),s=this._num("sensor.sem_battery_dynamic_floor_pct"),i=this._num("sensor.sem_battery_spendable_kwh"),r=this._hass.states["select.sem_battery_mode"]?"select.sem_battery_mode":null,a=this._hass.states["number.sem_battery_buffer_soc"]?"number.sem_battery_buffer_soc":null,n=this._hass.states["switch.sem_battery_may_assist_ev"]?"switch.sem_battery_may_assist_ev":null,o=this._num("sensor.sem_daily_battery_charge_energy"),l=this._num("sensor.sem_daily_battery_discharge_energy"),c=this._observer(),d=null!==e&&e<-50?this._tf("next_dev_batt_house",{kw:this._fmtKw(-e),soc:Math.round(t)}):null!==e&&e>50?this._tf("next_dev_batt_charging",{kw:this._fmtKw(e),soc:Math.round(t)}):this._tf("next_dev_batt_rest",{soc:Math.round(t)}),p=null!==s?this._tf("next_why_batt_floor_short",{floor:Math.round(s)}):"";return H`<div class="sec">
            <h3><span class="src"><i style="background:${Ye}"></i>${this._t("next_src_battery")}</span></h3>
            <div class="lead" style="font-size:1rem">${d}<small>${p}</small></div>
            <dl class="kv">
                ${r?H`<dt>${this._t("next_mode")}</dt><dd><select ?disabled=${c} @change=${t=>this._selectOption(r,t.target.value)}>
                    ${(this._attrs(r).options||[]).map(t=>H`<option value="${t}" ?selected=${t===this._str(r)}>${this._t("battery_mode_"+t)||t}</option>`)}</select></dd>`:K}
                ${a?H`<dt>${this._t("next_buffer")}</dt><dd><input type="number" ?disabled=${c} .value=${String(this._num(a)??"")} min="0" max="100" step="1" @change=${t=>this._setNumber(a,Number(t.target.value))}> %</dd>`:K}
                ${null!==o||null!==l?H`<dt>${this._t("next_today")}</dt><dd class="num">${this._t("next_in")} ${this._fmt(o,1)} · ${this._t("next_out")} ${this._fmt(l,1)} kWh</dd>`:K}
                ${null!==i?H`<dt>${this._t("next_spendable")}</dt><dd class="num">${this._fmt(i,1)} kWh</dd>`:K}
                <dt>${this._t("next_next")}</dt><dd>${this._nextBlock("battery")||this._t("next_follows_sun")}</dd>
            </dl>
            ${n?H`<label class="toggle"><input type="checkbox" ?disabled=${c} .checked=${"on"===this._str(n)} @change=${()=>this._toggleSwitch(n)}> ${this._t("next_may_feed_car")}</label>`:K}
        </div>`}_loads(){const t=this._attrs("sensor.sem_controllable_devices_count").devices||{},e=Object.entries(t);if(!e.length)return H`<div class="sec"><h3><span class="src"><i style="background:${Ze}"></i>${this._t("next_loads")}</span></h3>
                <div class="hint">${this._t("next_no_loads")}</div></div>`;const s=this._observer();return e.map(([t,e])=>{const i=e.power_entity?this._powerW(e.power_entity):null,r=e.switch_entity&&this._hass.states[e.switch_entity]?e.switch_entity:null,a=r?"on"===this._str(r):!!e.is_on,n=e.is_shed?this._t("next_dev_shed"):a?this._tf("next_dev_on",{kw:this._fmtKw(i??e.current_power??0)}):this._t("next_dev_off");return H`<div class="sec">
                <h3><span class="src"><i style="background:${Ze}"></i>${e.name||t}</span></h3>
                <div class="lead" style="font-size:1rem">${n}<small>${e.shed_reason||""}</small></div>
                <dl class="kv">
                    <dt>${this._t("next_mode")}</dt><dd>${e.control_mode?this._t("load_mode_"+e.control_mode)||e.control_mode:e.is_controllable?this._t("next_managed"):this._t("next_watch_only")}</dd>
                    <dt>${this._t("next_priority")}</dt><dd class="num">${e.priority??"—"}</dd>
                    ${e.power_rating?H`<dt>${this._t("next_rated")}</dt><dd class="num">${this._fmtKw(e.power_rating)} kW</dd>`:K}
                    <dt>${this._t("next_next")}</dt><dd>${this._nextBlock(`load:${t}`)||this._t("next_when_surplus")}</dd>
                </dl>
                ${r?H`<label class="toggle"><input type="checkbox" ?disabled=${s} .checked=${a} @change=${()=>this._toggleSwitch(r)}> ${this._t("next_switch_on")}</label>`:K}
            </div>`})}render(){if(!this._hass)return K;const t=this._chargers.length,e=this._chargers.filter(t=>(this._powerW(`sensor.sem_charger_${t}_power`)||0)>50).length,s=this._num("sensor.sem_battery_soc"),i=this._tf("next_dev_lead",{n:t+(null===s?0:1),charging:e});return H`<ha-card><div class="wrap">
            ${this._renderHead()}
            ${this._renderLead(i,this._t("next_dev_lead_sub"))}
            <div class="grid2">
                ${this._chargers.map(t=>this._charger(t))}
                ${this._battery()}
                ${this._loads()}
            </div>
        </div></ha-card>`}},{type:"sem-next-devices-card",name:"SEM Next · Devices",description:"Every charger, battery and load in one card shape: status, mode, targets, today, next, one change",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-next-devices-card",preview:!0});const vs={sunny:"☀️",mixed:"⛅",grey:"☁️",car:"🚗",cheap:"💸",negative:"💸",gap:"⚠️"},bs=["sunny","mixed","grey","car","cheap","negative","gap"];function xs(t){return!!t&&(!1!==t.selectable&&!(t.tags||[]).includes("gap"))}const $s=["last30","last90","last365"],ws={last30:30,last90:90,last365:365},ks=t=>(t||[]).filter(xs).map(t=>String(t.date)).sort();function Ss(t){return t.length?{from:t[0],to:t[t.length-1]}:null}function Cs(t,e){const s=ks(t),i=Math.max(0,Math.min(s.length,Math.round(Number(e)||0)));return i?Ss(s.slice(s.length-i)):null}function zs(t,e){const s=new Date(Date.UTC(t.getFullYear(),t.getMonth(),t.getDate()));return s.setUTCDate(s.getUTCDate()-e),s.toISOString().slice(0,10)}function Ms(t,e,s=new Date){const i=ws[e];if(!i)return null;const r=zs(s,i),a=zs(s,0);return Ss(ks(t).filter(t=>t>=r&&t<a))}function Ds(t,e){return e?ks(t).filter(t=>t>=e.from&&t<=e.to).length:0}function Es(t){const e=/^(\d{4})-(\d{2})-(\d{2})/.exec(String(t||""));return e?`${e[3]}.${e[2]}`:String(t||"")}function Ns(t,e="en"){const s=/^(\d{4})-(\d{2})-(\d{2})/.exec(String(t||""));if(!s)return String(t||"");const i=new Date(Date.UTC(+s[1],+s[2]-1,+s[3]));let r="";try{r=new Intl.DateTimeFormat(e,{weekday:"short",timeZone:"UTC"}).format(i)}catch(t){r=new Intl.DateTimeFormat("en",{weekday:"short",timeZone:"UTC"}).format(i)}return`${r} ${s[3]}.${s[2]}`}function Fs(t){const e=Number(t);if(null==t||!Number.isFinite(e))return"—";const s=Math.round(100*e)/100;return 0===s?"0.00":(s<0?"−":"")+Math.abs(s).toFixed(2)}function As(t){const e=Number(t);if(null==t||!Number.isFinite(e))return{text:"—",cls:"same"};const s=Math.round(100*e)/100;return 0===s?{text:"0.00",cls:"same"}:s<0?{text:"−"+Math.abs(s).toFixed(2),cls:"cheaper"}:{text:"+"+s.toFixed(2),cls:"dearer"}}function Ts(t,e){const s=Number(e),i=Number(t);if(!Number.isFinite(s)||!Number.isFinite(i)||0===s)return"";const r=Math.round(i/Math.abs(s)*1e3)/10;return 0===r?"0.0 %":(r<0?"−":"+")+Math.abs(r).toFixed(1)+" %"}const Is=["simulated","delta"];function Rs(t){return Is.includes(t)}const Bs=["sunny","mixed","grey","car","cheap"];function Os(t,e){const s=t||[];return e?s.filter(t=>(t.tags||[]).includes(e)):s}function Ls(t){const e=t||{},s=e.net_delta??null;return{days:Number(e.days)||0,actual:Fs(e.actual),simulated:Fs(e.simulated),delta:As(e.delta),net:null===s?null:As(s),pct:Ts(e.delta,e.actual),kwhOverLimit:Number(e.kwh_over_limit)||0,indicativeDays:Number(e.indicative_days)||0}}const Ps=t=>{const e=Number(t);return null!=t&&Number.isFinite(e)?e.toFixed(1):"—"};function Us(t){const e=t||{};return{capacity_kwh:e.capacity_kwh??"",reserve_pct:e.reserve_pct??"",peak_limit_kw:e.peak_limit_kw??"",import_mode:"recorded",import_rate:e.import_rate??"",export_mode:"recorded",export_rate:e.export_rate??"",battery_mode:e.battery_mode??"auto",ev_mode:"recorded",max_charge_w:e.max_charge_w??"",max_discharge_w:e.max_discharge_w??"",pv_mode:e.system_size_kwp?"kwp":"factor",pv_extra_kwp:"",pv_factor:1,battery_to_ev:!1!==e.battery_to_ev}}const Ws=["auto","self_consumption","force_charge","force_discharge","off"],Hs=["recorded","solar_only","solar_plus_battery","solar_plus_cheap","min_plus_solar","always_max","off"],js=t=>{if(""===t||null==t)return null;const e=Number(t);return Number.isFinite(e)?e:null};function Gs(t,e,s){const i=e||{},r=s||{};if("import_rate"===t)return"flat"===i.import_mode;if("export_rate"===t)return"flat"===i.export_mode;if("battery_mode"===t)return(i.battery_mode||"auto")!==(r.battery_mode||"auto");if("ev_mode"===t)return"recorded"!==(i.ev_mode||"recorded");if("battery_to_ev"===t)return!1!==i.battery_to_ev!=(!1!==r.battery_to_ev);if("pv"===t)return"kwp"===i.pv_mode?0!==(js(i.pv_extra_kwp)||0):1!==(js(i.pv_factor)??1);return js(r[t])!==js(i[t])}function Ks(t){const e=t||{},s={capacity_kwh:js(e.capacity_kwh),reserve_pct:js(e.reserve_pct)},i=js(e.peak_limit_kw);s.peak_limit_kw=i&&i>0?i:null;for(const t of["import","export"]){const i=js(e[`${t}_rate`]);s[`${t}_rate`]="flat"===e[`${t}_mode`]&&null!==i?i:"recorded"}e.battery_mode&&(s.battery_mode=e.battery_mode),s.ev_mode=e.ev_mode||"recorded";for(const t of["max_charge_w","max_discharge_w"]){const i=js(e[t]);null!==i&&(s[t]=i)}if("kwp"===e.pv_mode){const t=js(e.pv_extra_kwp);t&&(s.pv_extra_kwp=t)}else{const t=js(e.pv_factor);null!==t&&1!==t&&(s.pv_factor=t)}return!1===e.battery_to_ev&&(s.battery_to_ev=!1),s}const qs=["plus_battery","plus_pv","cheap_chargers","no_battery_ev"];function Vs(t,e,s){if(s?.running)return!1;if(!t?.from||!t?.to)return!1;const i=Ks(e);return null!==i.capacity_kwh&&i.capacity_kwh>0&&null!==i.reserve_pct}function Ys(t,e){let s=String(t||"");for(const[t,i]of Object.entries(e||{}))s=s.split(`{${t}}`).join(String(i));return s}const Zs="#8353d1",Xs={sunny:"sim_tag_sunny",mixed:"sim_tag_mixed",grey:"sim_tag_grey",car:"sim_tag_car",cheap:"sim_tag_cheap",negative:"sim_tag_cheap",gap:"sim_tag_gap"},Js={last30:"sim_pick_last30",last90:"sim_pick_last90",last365:"sim_pick_last365"},Qs=t=>`battery_mode_${t}`,ti=t=>"recorded"===t?"sim_as_recorded_opt":`charge_mode_${t}`,ei={sunny:"sim_tile_sunny",mixed:"sim_tile_mixed",grey:"sim_tile_grey",car:"sim_tile_car",cheap:"sim_tile_cheap"};kt("sem-simulation-card",class extends Lt{static get properties(){return{...super.properties,_days:{state:!0},_defaults:{state:!0},_form:{state:!0},_period:{state:!0},_status:{state:!0},_result:{state:!0},_expanded:{state:!0},_filter:{state:!0},_openDay:{state:!0},_error:{state:!0}}}constructor(){super(),this._days=null,this._defaults=null,this._form=null,this._period=null,this._status=null,this._result=null,this._expanded=!1,this._filter=null,this._openDay=null,this._error=null,this._pollTimer=null,this._loading=!1}set hass(t){const e=!this._hass;super.hass=t,e&&this.isConnected&&this._load()}get hass(){return this._hass}connectedCallback(){super.connectedCallback(),this._hass&&this._load()}disconnectedCallback(){super.disconnectedCallback(),this._stopPolling()}async _ws(t,e={}){return this._hass.callWS({type:`solar_energy_management/simulation/${t}`,...e})}async _load(){if(!this._loading&&this._hass?.callWS){this._loading=!0;try{const[t,e,s]=await Promise.all([this._ws("days").catch(()=>null),this._ws("defaults").catch(()=>null),this._ws("status").catch(()=>null)]);t&&(this._days=t),e&&(this._defaults=e,this._form||(this._form=Us(e))),this._onStatus(s),s?.running||this._result||await this._loadResult()}finally{this._loading=!1}}}_onStatus(t){t&&(this._status=t,t.running?this._schedulePoll():(this._stopPolling(),"failed"===t.status&&(this._error={kind:"failed",text:t.error||""})))}_schedulePoll(){!this._pollTimer&&this.isConnected&&(this._pollTimer=setTimeout(()=>this._poll(),2e3))}_stopPolling(){this._pollTimer&&clearTimeout(this._pollTimer),this._pollTimer=null}async _poll(){if(this._pollTimer=null,!this.isConnected||!this._hass?.callWS)return;let t=null;try{t=await this._ws("status")}catch(e){t=null}if(!this.isConnected)return;if(!t)return void this._schedulePoll();const e=this._status?.running;this._onStatus(t),e&&!t.running&&await this._loadResult(t.run_id)}async _loadResult(t){try{const e=await this._ws("result",t?{run_id:t}:{});this._result=e||null,this._expanded=!1,this._filter=null,this._openDay=null}catch(t){}}async _start(){if(!Vs(this._period,this._form,this._status))return;const t=(e=this._period,s=this._form,{from:e.from,to:e.to,params:Ks(s)});var e,s;this._error=null;try{await this._ws("start",t)}catch(t){const e=t?.code||"";return this._error="busy"===e?{kind:"busy"}:{kind:"invalid"===e?"invalid":"failed",text:t?.message||""},void("busy"===e&&this._poll())}this._status={running:!0,status:"running",done:0,total:Ds(this._days?.days,this._period),started_at:(new Date).toISOString()},this._schedulePoll()}async _cancel(){try{await this._ws("cancel")}catch(t){}this._stopPolling(),this._poll()}async _download(){try{const t=await this._ws("xlsx",this._result?.run_id?{run_id:this._result.run_id}:{});t?.base64&&(ys(t.filename||"sem-simulation.xlsx",t.base64,"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),"download"===this._error?.kind&&(this._error=null))}catch(t){console.warn("SEM: simulation download failed",t),this._error={kind:"download"}}}_setForm(t){this._form={...this._form||Us(this._defaults),...t}}_pickPeriod(t){this._period=Ms(this._days?.days||[],t)}_pickMonth(t){t&&(this._period=function(t,e){return Ss(ks(t).filter(t=>t.slice(0,7)===e))}(this._days?.days||[],t))}_pickRecent(t){this._period=Cs(this._days?.days||[],t)}_preset(t){let e=null;if("plus_pv"===t){const t=!!this._defaults?.system_size_kwp,s=globalThis.prompt?.(this._t(t?"sim_preset_pv_ask_kwp":"sim_preset_pv_ask_factor"));if(null==s||""===String(s).trim())return;if(e=Number(String(s).replace(",",".")),!Number.isFinite(e))return}this._form=function(t,e,s,i=null){const r={...t||Us(e)},a=e||{},n=(t,e)=>{const s=js(t)??js(e);return null===s?t:Math.round(2*s*10)/10};switch(s){case"plus_battery":r.capacity_kwh=n(r.capacity_kwh,a.capacity_kwh),r.max_charge_w=n(r.max_charge_w,a.max_charge_w),r.max_discharge_w=n(r.max_discharge_w,a.max_discharge_w);break;case"plus_pv":{const t=js(i);if(null===t)break;a.system_size_kwp?(r.pv_mode="kwp",r.pv_extra_kwp=t):(r.pv_mode="factor",r.pv_factor=t);break}case"cheap_chargers":r.ev_mode="solar_plus_cheap";break;case"no_battery_ev":r.battery_to_ev=!1}return r}(this._form,this._defaults,t,e)}_setFilter(t){this._filter=this._filter===t?null:t,this._expanded=!1,this._openDay=null}_toggleDay(t){this._openDay=this._openDay===t?null:t}_currency(){return this._result?.currency||this._defaults?.currency||ft(this._hass)||""}_est(){return H`<em class="est">${this._t("sim_est")}</em>`}_tagTitle(t){return(t||[]).map(t=>Xs[t]?this._t(Xs[t]):t).join(" · ")}_renderHeader(){if(!1===this._config?.header)return K;const t=this._days||{};return H`
            <ha-card><div class="header-wrap">
                <div class="icon-ring">
                    <svg viewBox="-34 -34 68 68"><circle r="28" fill="none" stroke="${Zs}" stroke-width="1.2" opacity=".25"></circle><circle r="24" fill="${Zs}0F" stroke="${Zs}" stroke-width="1.5"></circle></svg>
                    <ha-icon icon="mdi:flask-outline"></ha-icon>
                </div>
                <div class="title-area">
                    <div class="tab-title">${this._t("sim_title")}</div>
                    <div class="tab-subtitle">${this._t("sim_sub")}</div>
                </div>
                <div class="stats">
                    <div class="stat"><div class="stat-value">${t.stored??"—"}</div><div class="stat-label">${this._t("sim_days_stored")}</div></div>
                    <div class="stat"><div class="stat-value">${Ds(t.days,this._period)}</div><div class="stat-label">${this._t("sim_in_period")}</div></div>
                    <div class="stat"><div class="stat-value">${t.gaps??"—"}</div><div class="stat-label">${this._t("sim_data_gaps")}</div></div>
                </div>
            </div></ha-card>`}_renderPeriod(){const t=this._days?.days||[],e=function(t,e,s=new Date){if(!e)return null;for(const i of $s){const r=Ms(t,i,s);if(r&&r.from===e.from&&r.to===e.to)return i}return null}(t,this._period),s=this._period,i=Ds(t,s),r=function(t,e){return e?(t||[]).filter(t=>!xs(t)&&String(t.date)>=e.from&&String(t.date)<=e.to).length:0}(t,s);return H`
            <ha-card><div class="wrap">
                <div class="ct-title"><ha-icon icon="mdi:calendar-range"></ha-icon>${this._t("sim_period")}</div>
                ${t.length?H`
                    <div class="picks">
                        ${$s.map(t=>H`<span class="chip ${e===t?"on":""}" role="button" tabindex="0"
                            @click=${()=>this._pickPeriod(t)}>${this._t(Js[t])}</span>`)}
                        <select class="sel-ctl" aria-label="${this._t("sim_pick_month")}"
                            @change=${t=>{this._pickMonth(t.target.value),t.target.value=""}}>
                            <option value="">${this._t("sim_pick_month")}</option>
                            ${function(t){const e=new Set((t||[]).map(t=>String(t.date||"").slice(0,7)).filter(Boolean));return[...e].sort().reverse()}(t).map(t=>H`<option value="${t}">${t}</option>`)}
                        </select>
                    </div>
                    ${this._renderRecentSlider(t)}
                    <div class="span">${s?Ys(this._t("sim_period_span"),{from:Ns(s.from,this._hass?.language||"en"),to:Ns(s.to,this._hass?.language||"en"),n:i}):this._t("sim_pick_period_hint")}</div>
                    ${r>0?H`<div class="legend">${Ys(this._t("sim_period_gaps"),{n:r})}</div>`:K}
                    <div class="legend">${this._t("sim_period_note")}</div>`:H`
                    <div class="legend">${this._days?this._t("sim_no_days"):this._t("sim_loading")}</div>`}
            </div></ha-card>`}_renderRecentSlider(t){const e=function(t){return ks(t).length}(t);if(e<2)return K;const s=function(t,e){if(!e)return 0;const s=ks(t),i=s.filter(t=>t>=e.from&&t<=e.to);if(!i.length||i[i.length-1]!==s[s.length-1])return null;const r=Cs(t,i.length);return r&&r.from===e.from&&r.to===e.to?i.length:null}(t,this._period),i=s??0,r=i?Cs(t,i):null,a=r?`${Es(r.from)} – ${Es(r.to)}`:"";return H`
            <div class="recent">
                <label for="sim-recent">${i?Ys(this._t("sim_recent_n"),{n:i}):this._t("sim_recent_label")}</label>
                <input id="sim-recent" type="range" min="0" max="${e}" step="1" .value=${String(i)}
                    aria-valuetext="${i?Ys(this._t("sim_recent_n"),{n:i}):this._t("sim_recent_label")}"
                    @input=${t=>this._pickRecent(t.target.value)}>
                <small>${a}</small>
            </div>`}_renderNumberRow(t,e,s,i,r=null){const a=this._form||{},n=Gs(t,a,this._defaults);return H`
            <div class="ct-row">
                <span class="lbl">${this._t(e)}</span>
                <span class="cur">${i}</span><span class="arrow">→</span>
                <span class="inp ${n?"changed":""}"><input type="number" min="0" max="${r??K}" step="any"
                    .value=${String(a[t]??"")}
                    @change=${e=>this._setForm({[t]:e.target.value})}><small>${s}</small></span>
            </div>`}_renderRateRow(t,e){const s=this._form||{},i=s[`${t}_mode`]||"recorded",r=`${t}_rate`,a=Gs(r,s,this._defaults);return H`
            <div class="ct-row">
                <span class="lbl">${this._t(e)}</span>
                <span class="cur">${this._t("sim_as_recorded")}</span><span class="arrow">→</span>
                <select class="sel-ctl" .value=${i}
                    @change=${e=>this._setForm({[`${t}_mode`]:e.target.value})}>
                    <option value="recorded" ?selected=${"recorded"===i}>${this._t("sim_as_recorded_opt")}</option>
                    <option value="flat" ?selected=${"flat"===i}>${this._t("sim_flat")}</option>
                </select>
                ${"flat"===i?H`<span class="inp ${a?"changed":""}"><input type="number" step="any"
                    .value=${String(s[r]??"")}
                    @change=${t=>this._setForm({[r]:t.target.value})}><small>${this._currency()}/kWh</small></span>`:K}
            </div>`}_renderModeRow(t,e,s,i,r){const a=this._form||{},n=a[t]||s[0],o=Gs(t,a,this._defaults);return H`
            <div class="ct-row">
                <span class="lbl">${this._t(e)}</span>
                <span class="cur">${this._t(i(r))}</span><span class="arrow">→</span>
                <select class="sel-ctl ${o?"changed":""}" .value=${n}
                    @change=${e=>this._setForm({[t]:e.target.value})}>
                    ${s.map(t=>H`<option value="${t}" ?selected=${t===n}>${this._t(i(t))}</option>`)}
                </select>
            </div>`}_renderPvRow(){const t=this._form||{},e=this._defaults||{},s="kwp"===t.pv_mode&&e.system_size_kwp,i=Gs("pv",t,e);return H`
            <div class="ct-row">
                <span class="lbl">${this._t("sim_pv")}</span>
                <span class="cur">${e.system_size_kwp?`${e.system_size_kwp} kWp`:this._t("sim_as_recorded")}</span><span class="arrow">→</span>
                ${e.system_size_kwp?H`<select class="sel-ctl" .value=${t.pv_mode||"kwp"}
                    @change=${t=>this._setForm({pv_mode:t.target.value})}>
                    <option value="kwp" ?selected=${"kwp"===t.pv_mode}>${this._t("sim_pv_kwp")}</option>
                    <option value="factor" ?selected=${"kwp"!==t.pv_mode}>${this._t("sim_pv_factor")}</option>
                </select>`:K}
                <span class="inp ${i?"changed":""}"><input type="number" min="0" step="any"
                    .value=${String((s?t.pv_extra_kwp:t.pv_factor)??"")}
                    @change=${t=>this._setForm(s?{pv_extra_kwp:t.target.value}:{pv_factor:t.target.value})}><small>${s?"kWp":"×"}</small></span>
            </div>`}_renderEvAssistRow(){const t=this._form||{},e=this._defaults||{},s=!1===t.battery_to_ev?"no":"yes",i=Gs("battery_to_ev",t,e);return H`
            <div class="ct-row">
                <span class="lbl">${this._t("sim_battery_to_ev")}</span>
                <span class="cur">${this._t(!1===e.battery_to_ev?"sim_no":"sim_yes")}</span><span class="arrow">→</span>
                <select class="sel-ctl ${i?"changed":""}" .value=${s}
                    @change=${t=>this._setForm({battery_to_ev:"no"!==t.target.value})}>
                    <option value="yes" ?selected=${"yes"===s}>${this._t("sim_yes")}</option>
                    <option value="no" ?selected=${"no"===s}>${this._t("sim_no")}</option>
                </select>
            </div>`}_renderWhatIf(){const t=this._defaults;if(!t)return K;const e=t.peak_limit_kw?`${t.peak_limit_kw} kW`:this._t("sim_none"),s=t=>t?`${t} W`:"—";return H`
            <ha-card><div class="wrap">
                <div class="ct-title"><ha-icon icon="mdi:tune-variant"></ha-icon>${this._t("sim_what_if")}</div>
                <div class="picks" aria-label="${this._t("sim_presets")}">
                    <span class="lbl-small">${this._t("sim_presets")}</span>
                    ${qs.map(t=>H`<span class="chip" role="button" tabindex="0"
                        @click=${()=>this._preset(t)}>${this._t((t=>`sim_preset_${t}`)(t))}</span>`)}
                </div>
                <div class="group">
                    ${this._renderNumberRow("capacity_kwh","sim_battery_size","kWh",`${t.capacity_kwh??"—"} kWh`,150)}
                    ${this._renderNumberRow("max_charge_w","sim_charge_power","W",s(t.max_charge_w))}
                    ${this._renderNumberRow("max_discharge_w","sim_discharge_power","W",s(t.max_discharge_w))}
                    ${this._renderNumberRow("reserve_pct","sim_battery_reserve","%",`${t.reserve_pct??"—"} %`)}
                    ${this._renderNumberRow("peak_limit_kw","sim_peak_limit","kW",e)}
                    ${this._renderPvRow()}
                    ${this._renderRateRow("import","sim_import_price")}
                    ${this._renderRateRow("export","sim_export_value")}
                    ${this._renderModeRow("battery_mode","sim_battery_mode",Ws,Qs,t.battery_mode||"auto")}
                    ${this._renderModeRow("ev_mode","sim_ev_mode",Hs,ti,"recorded")}
                    ${this._renderEvAssistRow()}
                </div>
            </div></ha-card>`}_renderRun(){const t=this._status||{},e=!!t.running,s=Vs(this._period,this._form,t),i=e?function(t,e=Date.now()){const s=Number(t?.done)||0,i=Number(t?.total)||0,r=Date.parse(t?.started_at||"");if(!s||!i||s>=i||!Number.isFinite(r))return null;const a=(e-r)/s;return a>0?Math.max(1,Math.ceil(a*(i-s)/6e4)):null}(t):null,r=Ds(this._days?.days,this._period);let a="";e&&(a=Ys(this._t("sim_running"),{x:Math.min((t.done||0)+1,t.total||0),y:t.total||0}),null!==i&&(a+=" · "+Ys(this._t("sim_minutes_left"),{n:i})));const n=this._error;let o="";return"busy"===n?.kind?o=this._t("sim_busy"):"failed"!==n?.kind&&"invalid"!==n?.kind||(o=Ys(this._t("sim_failed"),{error:n.text||""})),H`
            <ha-card><div class="wrap">
                <div class="runrow">
                    <button class="btn" ?disabled=${!s} @click=${()=>this._start()}>
                        <ha-icon icon="mdi:play"></ha-icon>${this._t("sim_run")}</button>
                    <div class="prog">
                        ${e?H`
                            <div class="bar"><i style="width:${Math.round(100*function(t){const e=Number(t?.done)||0,s=Number(t?.total)||0;return s>0?Math.min(1,e/s):0}(t))}%"></i></div>
                            <small>${a}</small>`:H`
                            <small>${r?Ys(this._t("sim_n_days"),{n:r}):this._t("sim_pick_period_hint")}</small>`}
                    </div>
                    ${e?H`<button class="btn sec" @click=${()=>this._cancel()}>
                        <ha-icon icon="mdi:stop"></ha-icon>${this._t("sim_stop")}</button>`:K}
                </div>
                ${o?H`<div class="err">${o}</div>`:K}
            </div></ha-card>`}_renderDetail(t){const e=function(t){const e=t||{},s=t=>({actual:Ps(e[`actual_${t}_kwh`]),simulated:Ps(e[`simulated_${t}_kwh`])});return{lines:[{key:"sim_grid_in",...s("grid_import")},{key:"sim_grid_out",...s("grid_export")},{key:"sim_batt_in",...s("battery_charge")},{key:"sim_batt_out",...s("battery_discharge")},{key:"sim_pack_end",actual:Ps(e.actual_end_kwh),simulated:Ps(e.simulated_end_kwh)}],net:void 0===e.net_delta||null===e.net_delta?null:As(e.net_delta),story:[...e.story||[]]}}(t);return H`
            <div class="detail">
                ${e.lines.map(t=>H`<div class="dl"><span>${this._t(t.key)}</span>
                    <span class="num">${t.actual} → ${t.simulated} kWh ${this._est()}</span></div>`)}
                ${e.net?H`<div class="dl"><span>${Ys(this._t("sim_day_net"),{d:""})}</span>
                    <span class="num delta ${e.net.cls}">${e.net.text}</span></div>`:K}
                ${e.story.length?H`<div class="why">${e.story.join(" · ")}</div>`:K}
            </div>`}_renderRow(t,e){const s=As(t.delta),i=(t.reasons||[]).join(" · "),r=this._openDay===t.date;return H`
            <div class="trow tap ${r?"open":""}" role="button" tabindex="0" aria-expanded="${r?"true":"false"}"
                @click=${()=>this._toggleDay(t.date)}>
                <span class="c1">${Ns(t.date,e)}${t.indicative?H` <span class="warn"
                    title="${this._t("sim_indicative")}${i?": "+i:""}">⚠️</span>`:K}</span>
                <span class="c2" title="${this._tagTitle(t.tags)}">${function(t){const e=new Set(t||[]),s=[];for(const t of bs)e.has(t)&&!s.includes(vs[t])&&s.push(vs[t]);return s.join("")}(t.tags)}</span>
                <span class="num">${Fs(t.actual_cost)}${Rs("actual")?this._est():K}</span>
                <span class="num">${Fs(t.simulated_cost)} ${Rs("simulated")?this._est():K}</span>
                <span class="num delta ${s.cls}">${s.text} ${Rs("delta")?this._est():K}</span>
            </div>
            ${r?this._renderDetail(t):K}`}_renderMonths(t){const{rows:e,helps:s}=function(t){const e=(t||[]).map(t=>({month:String(t.month||""),days:Number(t.days)||0,delta:As(t.net_delta??t.delta),value:Number(t.net_delta??t.delta)||0})),s=Math.max(0,...e.map(t=>Math.abs(t.value)));for(const t of e)t.share=s>0?Math.abs(t.value)/s:0;const i=e.filter(t=>Math.round(100*t.value)<0).map(t=>t.month);return{rows:e,helps:i}}(t.months);return e.length<2?K:H`
            <div class="ct-title sub"><ha-icon icon="mdi:calendar-month"></ha-icon>${this._t("sim_months")}</div>
            ${e.map(t=>H`
                <div class="mrow"><span>${t.month}</span>
                    <span class="mbar"><i class="${t.delta.cls}" style="width:${Math.round(100*t.share)}%"></i></span>
                    <span class="num delta ${t.delta.cls}">${t.delta.text}</span></div>`)}
            <div class="legend">${s.length?Ys(this._t("sim_months_helps"),{months:s.join(", ")}):this._t("sim_months_none")} ${this._est()}</div>`}_renderEnergy(t){const e=function(t){const e=t?.actual||{},s=t?.simulated||{};if(!t?.actual&&!t?.simulated)return[];const i=t=>null==t?"—":`${Number(t).toFixed(1)} %`,r=t=>null==t?"—":Number(t).toFixed(1);return[{key:"sim_grid_in",actual:Ps(e.grid_import_kwh),simulated:Ps(s.grid_import_kwh),unit:"kWh"},{key:"sim_grid_out",actual:Ps(e.grid_export_kwh),simulated:Ps(s.grid_export_kwh),unit:"kWh"},{key:"sim_self_use",actual:i(e.self_consumption_pct),simulated:i(s.self_consumption_pct),unit:""},{key:"sim_cycles",actual:r(e.cycles),simulated:r(s.cycles),unit:""}]}(t.energy);return e.length?H`
            <div class="ct-title sub"><ha-icon icon="mdi:lightning-bolt"></ha-icon>${this._t("sim_energy")}
                <span class="right muted">${this._t("sim_actual_word")} → ${this._t("sim_simulated_word")}</span></div>
            ${e.map(t=>H`<div class="dl"><span>${this._t(t.key)}</span>
                <span class="num">${t.actual} → ${t.simulated}${t.unit?" "+t.unit:""} ${this._est()}</span></div>`)}`:K}_renderResults(){const t=this._result;if(!t)return K;const e=this._hass?.language||"en",s=this._currency(),i=this._filter,{rows:r,more:a}=function(t,e=!1,s=8){const i=[...t||[]].sort((t,e)=>String(e.date).localeCompare(String(t.date)));return e||i.length<=s?{rows:i,more:0}:{rows:i.slice(0,s),more:i.length-s}}(Os(t.days,i),this._expanded),n=function(t,e,s=null){const i=Number(e?.days)||0,r=[];for(const e of Bs){const a=t?.[e]||{},n=Number(a.days)||0;if("cheap"===e&&0===n)continue;const o="sunny"===e||"mixed"===e||"grey"===e;r.push({tag:e,glyph:vs[e],days:n,of:o?null:i,delta:n?As(a.delta):null,actual:n?Number(a.actual)||0:null,simulated:n?Number(a.simulated)||0:null,on:s===e})}return r}(t.per_tag,t.total,i),o=Ls(function(t,e){return e?t?.per_tag?.[e]||{days:0}:t?.total||{}}(t,i)),l=Ls(t.total),c=t.skipped||[],d=function(t){const e=t?.calibration,s=t=>null==t?null:Number(t);if(!e||void 0===t?.calibrated)return{ok:!0,caution:!1,pct:null,days:null,leftOut:0,carDays:0,carPct:null,repriced:!1};const i=s(e.error_pct),r=s(e.max_pct);return{ok:!!t.calibrated,caution:!!t.calibrated&&null!==i&&null!==r&&i>r,pct:i,days:s(e.days),leftOut:Number(e.left_out)||0,carDays:Number(e.car_days)||0,carPct:s(e.car_error_pct),repriced:!!t.repriced}}(t);if(!d.ok)return H`
            <ha-card><div class="wrap">
                <div class="ct-title"><ha-icon icon="mdi:chart-box-outline"></ha-icon>${this._t("sim_results")} · ${Ys(this._t("sim_last_run"),{n:l.days})}</div>
                <div class="err">${Ys(this._t("sim_cant_simulate"),{pct:null===d.pct?"?":d.pct})}</div>
                ${this._renderCalibLines(d)}
                <div class="legend">${this._t("sim_limits")}</div>
            </div></ha-card>`;const p=t.stored_energy||null,_=t.ev||null,h=Number(_?.not_delivered_kwh)||0;return H`
            <ha-card><div class="wrap">
                <div class="ct-title"><ha-icon icon="mdi:chart-box-outline"></ha-icon>${this._t("sim_results")} · ${Ys(this._t("sim_last_run"),{n:l.days})}
                    <span class="right" role="button" tabindex="0" @click=${()=>this._download()}>
                        <ha-icon icon="mdi:download"></ha-icon>${this._t("sessions_xlsx")}</span></div>
                ${t.cancelled?H`<div class="note">${this._t("sim_cancelled")}</div>`:K}
                ${"download"===this._error?.kind?H`<div class="err">${this._t("sessions_download_failed")}</div>`:K}
                ${l.net?H`<div class="headline">
                    <span>${this._t("sim_net_total")}</span>
                    <b class="delta ${l.net.cls}">${l.net.text} ${s} ${this._est()}</b>
                    <small>${this._t("sim_col_diff")} ${l.delta.text} ${s}</small></div>`:K}
                <div class="tiles">
                    <div class="tile tap ${i?"":"on"}" role="button" tabindex="0" @click=${()=>this._setFilter(null)}>
                        <div class="v ${l.delta.cls}">${l.delta.text}</div>
                        <div class="l">${this._t("sim_filter_all")} · ${Ys(this._t("sim_n_days"),{n:l.days})}</div>
                    </div>
                    ${n.map(t=>H`
                        <div class="tile tap ${t.on?"on":""} ${t.days?"":"empty"}" role="button" tabindex="0"
                            @click=${()=>t.days&&this._setFilter(t.tag)}>
                            <div class="v ${t.delta?t.delta.cls:"none"}">${t.delta?t.delta.text:"—"}</div>
                            <div class="l">${t.glyph} ${this._t(ei[t.tag])} · ${t.days?null===t.of?Ys(this._t("sim_n_days"),{n:t.days}):Ys(this._t("sim_n_of"),{n:t.days,m:t.of}):this._t("sim_none_in_period")}</div>
                        </div>`)}
                </div>
                <div class="legend">${this._t("sim_filter_hint")}</div>
                <div class="thead"><span>${this._t("sim_col_day")}</span><span>${this._t("sim_col_tags")}</span>
                    <span class="num">${this._t("sim_col_actual")}${d.repriced?"*":""} ${s}</span>
                    <span class="num">${this._t("sim_col_simulated")} ${s}</span>
                    <span class="num">${this._t("sim_col_diff")}</span></div>
                ${r.map(t=>this._renderRow(t,e))}
                ${a>0?H`<div class="more" role="button" tabindex="0"
                    @click=${()=>{this._expanded=!0}}>${Ys(this._t("sim_more_days"),{n:a})} ▾</div>`:K}
                ${this._expanded&&Os(t.days,i).length>8?H`<div class="more" role="button" tabindex="0"
                    @click=${()=>{this._expanded=!1}}>${this._t("sim_fewer")} ▴</div>`:K}
                <div class="total">
                    <span>${i?H`${ei[i]?this._t(ei[i]):i} · `:K}${Ys(this._t("sim_n_days"),{n:o.days})} · ${this._t("sim_actual_word")} <b>${o.actual}</b> → ${this._t("sim_simulated_word")} <b>${o.simulated} ${this._est()}</b> ${s}</span>
                    <span class="delta ${o.delta.cls}">${o.delta.text} ${s}${o.pct?" · "+o.pct:""}</span>
                </div>
                ${i&&o.net?H`<div class="legend">${Ys(this._t("sim_day_net"),{d:o.net.text+" "+s})} ${this._est()}</div>`:K}
                ${p&&Math.abs(Number(p.kwh)||0)>=.05?H`<div class="legend">${Ys(this._t("sim_stored_sum"),{kwh:(Number(p.kwh)>=0?"+":"")+Number(p.kwh).toFixed(1),value:Fs(p.value)+" "+s})} ${this._est()}</div>`:K}
                ${this._renderMonths(t)}
                ${this._renderEnergy(t)}
                ${_&&((Number(_.moved_kwh)||0)>0||(Number(_.not_delivered_kwh)||0)>0)?H`<div class="legend">${Ys(this._t("sim_ev_moved"),{moved:Number(_.moved_kwh).toFixed(1),short:Number(_.not_delivered_kwh).toFixed(1)})} ${this._est()}</div>`:K}
                ${h>0&&l.net?H`<div class="legend">${Ys(this._t("sim_net_ev_note"),{kwh:h.toFixed(1),value:Fs(_.not_delivered_value)+" "+s})} ${this._est()}</div>`:K}
                ${d.repriced?H`<div class="legend">${this._t("sim_repriced_note")}</div>`:K}
                ${this._renderCalibLines(d)}
                ${l.kwhOverLimit>0?H`<div class="legend">${Ys(this._t("sim_over_limit"),{n:l.kwhOverLimit.toFixed(1)})} ${this._est()}</div>`:K}
                ${c.length?H`<div class="legend" title="${c.map(t=>`${t.date}: ${t.reason}`).join("\n")}">${Ys(this._t("sim_skipped"),{n:c.length})}</div>`:K}
                <div class="legend">${this._est()} ${this._t("sim_est_legend")}</div>
                <div class="legend">${this._t("sim_limits")}</div>
            </div></ha-card>`}_renderCalibLines(t){return H`
            ${t.caution?H`<div class="warn">${Ys(this._t("sim_caution"),{pct:t.pct})}</div>`:K}
            ${null===t.days?K:H`<div class="legend">${Ys(this._t("sim_days_checked"),{n:t.days,m:t.leftOut})}</div>`}
            ${t.carDays>0&&null!==t.carPct?H`<div class="legend">${Ys(this._t("sim_car_error"),{pct:t.carPct,n:t.carDays})}</div>`:K}`}render(){return H`
            <div class="sim">
                ${this._renderHeader()}
                ${this._renderPeriod()}
                ${this._renderWhatIf()}
                ${this._renderRun()}
                ${this._renderResults()}
            </div>`}getCardSize(){return 12}static get styles(){return[Ot,a`
            :host { display: block; }
            .sim { color: var(--primary-text-color); }
            ha-card { display: block; margin: 8px 0; overflow: hidden; }
            .wrap {
                padding: 14px 20px; position: relative;
                background: radial-gradient(ellipse 70% 60% at 50% 25%, #8353d10f 0%, transparent 100%),
                    radial-gradient(circle at 2px 2px, rgba(128,128,128,0.05) 0.7px, transparent 0.7px);
                background-size: 100% 100%, 50px 50px;
            }
            .header-wrap {
                display: flex; align-items: center; gap: 16px; padding: 16px 20px;
                background: radial-gradient(ellipse 80% 70% at 20% 50%, #8353d10d 0%, transparent 70%),
                    radial-gradient(circle at 2px 2px, rgba(128,128,128,0.05) 0.7px, transparent 0.7px);
                background-size: 100% 100%, 50px 50px;
            }
            .icon-ring { position: relative; flex-shrink: 0; width: 64px; height: 64px; }
            .icon-ring svg { width: 100%; height: 100%; }
            .icon-ring ha-icon {
                position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
                color: #8353d1; --mdc-icon-size: 26px; opacity: .85;
            }
            .title-area { flex: 1 1 auto; min-width: 140px; }
            .tab-title { font-size: 20px; font-weight: 700; color: #8353d1; letter-spacing: .5px; text-shadow: 0 0 12px #8353d140; }
            .tab-subtitle { font-size: 12px; color: var(--secondary-text-color); margin-top: 2px; font-weight: 500; }
            .stats { display: flex; gap: 16px; flex-shrink: 0; }
            .stat { text-align: center; min-width: 50px; }
            .stat-value { font-size: 15px; font-weight: 700; font-variant-numeric: tabular-nums; }
            .stat-label { font-size: 11px; color: var(--secondary-text-color); font-weight: 500; margin-top: 1px; }
            .ct-title {
                font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: var(--secondary-text-color);
                display: flex; align-items: center; gap: 5px; margin-bottom: 6px;
            }
            .ct-title ha-icon { --mdc-icon-size: 14px; color: #8353d1; }
            .ct-title .right {
                margin-left: auto; text-transform: none; letter-spacing: 0; font-size: 12px; font-weight: 600;
                color: #5BC8D8; display: flex; gap: 4px; align-items: center; cursor: pointer;
            }
            .ct-title .right ha-icon { color: #5BC8D8; }
            .chip {
                display: inline-flex; align-items: center; gap: 4px; background: var(--secondary-background-color);
                border: 1px solid var(--divider-color); border-radius: 12px; padding: 3px 10px; font-size: 11px;
                font-weight: 500; font-variant-numeric: tabular-nums; cursor: pointer; user-select: none;
            }
            .chip.on { background: #8353d122; border-color: #8353d1; color: #8353d1; font-weight: 700; }
            .picks { display: flex; gap: 6px; flex-wrap: wrap; margin: 2px 0 10px; }
            .recent { display: grid; grid-template-columns: 1fr auto; gap: 2px 8px; align-items: center; margin: 0 0 10px; font-size: 12px; }
            .recent label { font-weight: 600; }
            .recent small { color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
            .recent input { grid-column: 1 / -1; width: 100%; min-height: 36px; accent-color: #8353d1; }
            .span { font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }
            .lbl-small { font-size: 11px; color: var(--secondary-text-color); align-self: center; }
            .legend { font-size: 11px; color: var(--secondary-text-color); margin-top: 8px; }
            .note { font-size: 12px; color: var(--secondary-text-color); margin: 2px 0 6px; }
            .err { font-size: 12px; color: var(--error-color, #db4437); margin-top: 8px; }
            .warn { font-size: 12px; color: var(--warning-color, #ff9800); margin-top: 8px; }
            .group {
                margin-top: 8px; padding: 6px 12px; border: 1px solid var(--divider-color);
                border-radius: 10px; background: rgba(255,255,255,0.025);
            }
            .ct-row { display: flex; align-items: center; min-height: 34px; gap: 8px; border-bottom: 1px solid var(--divider-color); }
            .ct-row:last-child { border-bottom: 0; }
            .ct-row .lbl { flex: 1 1 auto; font-size: 12px; font-weight: 500; }
            .cur { font-size: 11px; color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
            .arrow { color: var(--secondary-text-color); font-size: 12px; }
            .inp {
                display: inline-flex; align-items: center; gap: 4px; background: var(--secondary-background-color);
                border: 1px solid var(--divider-color); border-radius: 8px; padding: 3px 8px; font-size: 12px;
                font-weight: 700; font-variant-numeric: tabular-nums; min-width: 56px; justify-content: flex-end;
            }
            .inp input {
                width: 48px; border: 0; background: transparent; color: inherit; font: inherit; text-align: right;
                padding: 0; -moz-appearance: textfield;
            }
            .inp input::-webkit-outer-spin-button, .inp input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
            .inp input:focus { outline: none; }
            .inp.changed, .sel-ctl.changed { border-color: #8353d1; color: #8353d1; }
            .inp small { font-weight: 500; color: var(--secondary-text-color); }
            .sel-ctl {
                appearance: none; -webkit-appearance: none; background-color: var(--secondary-background-color);
                background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23bbbbbb' d='M7 10l5 5 5-5z'/%3E%3C/svg%3E");
                background-repeat: no-repeat; background-position: right 6px center; background-size: 14px;
                color: var(--primary-text-color); border: 1px solid var(--divider-color); border-radius: 8px;
                padding: 4px 24px 4px 10px; font-size: 12px; font-weight: 700; font-family: inherit;
            }
            .runrow { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
            .btn {
                display: inline-flex; align-items: center; gap: 6px; border-radius: 10px; padding: 8px 16px;
                font-size: 13px; font-weight: 700; border: 1px solid #8353d1; background: #8353d1; color: #fff;
                cursor: pointer; font-family: inherit;
            }
            .btn[disabled] { opacity: .45; cursor: not-allowed; }
            .btn.sec { background: transparent; color: var(--primary-text-color); border-color: var(--divider-color); }
            .btn ha-icon { --mdc-icon-size: 16px; }
            .prog { flex: 1 1 220px; display: flex; flex-direction: column; gap: 4px; }
            .bar { height: 6px; border-radius: 3px; background: var(--secondary-background-color); overflow: hidden; }
            .bar i { display: block; height: 100%; background: linear-gradient(90deg, #8353d1, #5BC8D8); transition: width .4s; }
            .prog small { font-size: 11px; color: var(--secondary-text-color); }
            .trow, .thead {
                display: grid; grid-template-columns: 1.5fr 1fr .9fr 1.1fr 1.1fr; gap: 6px; align-items: center;
                min-height: 28px; border-bottom: 1px solid var(--divider-color); font-size: 12px;
                font-variant-numeric: tabular-nums;
            }
            .thead { font-size: 11px; font-weight: 500; color: var(--secondary-text-color); min-height: 22px; }
            .num { text-align: right; }
            .warn { font-size: 11px; cursor: help; }
            .delta { font-weight: 700; }
            .cheaper { color: #8DC892; }
            .dearer { color: #ff9800; }
            .same, .none { color: var(--secondary-text-color); }
            .est {
                font-style: normal; font-size: 9px; font-weight: 600; color: #8353d1; border: 1px solid #8353d166;
                border-radius: 6px; padding: 0 4px; vertical-align: middle;
            }
            .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; margin-top: 10px; }
            .tile { border: 1px solid var(--divider-color); border-radius: 10px; padding: 8px 10px; background: rgba(255,255,255,0.025); }
            .tile .v { font-size: 16px; font-weight: 700; font-variant-numeric: tabular-nums; }
            .tile .l { font-size: 11px; color: var(--secondary-text-color); font-weight: 500; }
            .total { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; flex-wrap: wrap; margin-top: 10px; font-size: 12px; }
            .total b { font-size: 14px; }
            .more { font-size: 11px; color: var(--secondary-text-color); padding: 6px 0 0; cursor: pointer; }
            .tap { cursor: pointer; }
            .tile.on { border-color: #8353d1; background: #8353d11c; }
            .tile.empty { opacity: .55; cursor: default; }
            .trow.open { background: #8353d10f; }
            .detail { padding: 6px 8px 8px; border-bottom: 1px solid var(--divider-color); background: #8353d108; }
            .dl { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; min-height: 22px; align-items: center; font-variant-numeric: tabular-nums; }
            .why { font-size: 11px; color: var(--secondary-text-color); margin-top: 4px; }
            .headline { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin: 4px 0 8px; font-size: 13px; }
            .headline b { font-size: 18px; }
            .headline small { color: var(--secondary-text-color); }
            .ct-title.sub { margin-top: 14px; }
            .ct-title .right.muted { color: var(--secondary-text-color); cursor: default; font-weight: 500; }
            .mrow { display: grid; grid-template-columns: 80px 1fr auto; gap: 8px; align-items: center; font-size: 12px; min-height: 22px; font-variant-numeric: tabular-nums; }
            .mbar { height: 6px; border-radius: 3px; background: var(--secondary-background-color); overflow: hidden; }
            .mbar i { display: block; height: 100%; }
            .mbar i.cheaper { background: #8DC892; }
            .mbar i.dearer { background: #ff9800; }
            .mbar i.same { background: var(--divider-color); }
            @media (max-width: 600px) {
                .header-wrap { flex-wrap: wrap; }
                .trow, .thead { grid-template-columns: 1.3fr .8fr .9fr 1.1fr 1.1fr; font-size: 11px; }
                .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); }
                .mrow { grid-template-columns: 64px 1fr auto; }
            }
        `]}},{type:"sem-simulation-card",name:"SEM Simulation",description:"Replay a recorded period with another battery, solar size, peak limit or price; estimated cost per day type and month",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-simulation-card"});const si={day:{solar:"daily_solar_energy",grid_in:"daily_grid_import_energy",grid_out:"daily_grid_export_energy",battery:"daily_battery_discharge_energy",car:"daily_ev_energy",house:"daily_home_energy",cost:"daily_costs",saved:"daily_savings",batt_saved:"daily_battery_savings",export_rev:"daily_export_revenue",co2:"daily_co2_avoided",forecast:"forecast_today_kwh"},month:{solar:"monthly_solar_yield_energy",grid_in:"monthly_grid_import_energy",grid_out:"monthly_grid_export_energy",battery:"monthly_battery_discharge_energy",car:"monthly_ev_consumption_energy",house:"monthly_home_consumption_energy",cost:"monthly_costs",saved:"monthly_savings",batt_saved:"monthly_battery_savings",export_rev:"monthly_export_revenue"},year:{solar:"yearly_solar_yield_energy",grid_in:"yearly_grid_import_energy",grid_out:"yearly_grid_export_energy",battery:"yearly_battery_discharge_energy",car:"yearly_ev_energy",house:"yearly_home_consumption_energy",cost:"yearly_costs",saved:"yearly_savings",batt_saved:"yearly_battery_savings",export_rev:"yearly_export_revenue",co2:"yearly_co2_avoided",lifetime:"lifetime_total_savings"}},ii=[["solar","next_src_solar",Ge],["grid_in","next_grid_in",Ke],["battery","next_src_battery",Ye],["car","next_src_car",Xe],["grid_out","next_export",qe]];kt("sem-next-insights-card",class extends ss{static get properties(){return{_period:{state:!0},_tab:{state:!0}}}static get styles(){return es}constructor(){super(),this._period="day",this._tab="energy"}_watchIds(){const t=[];for(const e of Object.values(si))for(const s of Object.values(e))t.push(`sensor.sem_${s}`);return[...super._watchIds(),...t]}_v(t){const e=si[this._period][t];return e?this._num(`sensor.sem_${e}`):null}_lead(){const t=this._v("house"),e=this._v("solar"),s=this._v("cost"),i=this._v("saved"),r=this._currency();if("money"===this._tab&&null!==s)return this._tf("next_ins_lead_money",{period:this._t("next_period_"+this._period),cost:this._fmt(s,2),saved:this._fmt(i??0,2),cur:r});if(null!==t&&null!==e){const s=this._v("forecast"),i="day"===this._period&&s?" "+this._tf("next_pct_forecast",{pct:Math.round(e/s*100)}):"";return this._tf("next_ins_lead_energy",{period:this._t("next_period_"+this._period),house:this._fmt(t,1),solar:this._fmt(e,1)})+i}return this._t("next_ins_lead_none")}_energy(){const t=ii.map(([t,e,s])=>({v:this._v(t),label:this._t(e),color:s})).filter(t=>null!==t.v);if(!t.length)return K;const e=Math.max(1,...t.map(t=>t.v));return H`<div class="sec wide"><h3>${this._t("next_where_from")}</h3><div class="list" style="gap:6px">
            ${t.map(t=>H`<div style="display:grid;grid-template-columns:90px 1fr 72px;align-items:center;gap:8px;font-size:0.85rem">
                <span class="src"><i style="background:${t.color}"></i>${t.label}</span>
                <div class="bar" style="height:12px;border-radius:6px"><i style="width:${Math.max(2,t.v/e*100)}%;background:${t.color}"></i></div>
                <em class="num" style="font-style:normal;text-align:right;font-weight:600">${t.v>=100?Math.round(t.v):this._fmt(t.v,1)} kWh</em></div>`)}
        </div></div>`}_money(){const t=this._currency(),e=[["cost","next_cost"],["saved","next_saved"],["batt_saved","next_batt_saved"],["export_rev","next_export_revenue"],["lifetime","next_lifetime_saved"]].map(([t,e])=>({v:this._v(t),label:this._t(e),money:!0})).concat([{v:this._v("co2"),label:this._t("next_co2_avoided"),money:!1}]).filter(t=>null!==t.v);return e.length?H`<div class="sec"><h3>${this._t("next_money")}</h3><dl class="kv">
            ${e.map(e=>H`<dt>${e.label}</dt><dd class="num">${this._fmt(e.v,e.money?2:1)} ${e.money?t:this._kgUnit("daily_co2_avoided")}</dd>`)}
        </dl></div>`:K}_replay(){return H`<div class="sec wide"><h3>${this._t("next_replay")}</h3>
            <div class="hint">${this._t("next_replay_hint")}</div>
            <sem-simulation-card .hass=${this._hass}></sem-simulation-card>
        </div>`}updated(){super.updated();const t=this.renderRoot?.querySelector("sem-simulation-card");if(t&&!t._semNextConfigured){t._semNextConfigured=!0;try{t.setConfig({})}catch(t){}t.hass=this._hass}}render(){if(!this._hass)return K;const t=(t,e,s)=>H`<div class="sub">${t.map(([t,i])=>H`<button aria-pressed="${e===t}" @click=${()=>s(t)}>${this._t(i)}</button>`)}</div>`;return H`<ha-card><div class="wrap">
            ${this._renderHead()}
            <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
                ${t([["day","next_period_day"],["month","next_period_month"],["year","next_period_year"]],this._period,t=>{this._period=t})}
                ${t([["energy","next_tab_energy"],["money","next_tab_money"],["replay","next_replay"]],this._tab,t=>{this._tab=t})}
            </div>
            ${"replay"===this._tab?K:this._renderLead(this._lead(),"")}
            <div class="grid2">
                ${"energy"===this._tab?this._energy():K}
                ${"replay"!==this._tab?this._money():K}
                ${"replay"===this._tab?this._replay():K}
            </div>
        </div></ha-card>`}},{type:"sem-next-insights-card",name:"SEM Next · Insights",description:"One period selector: where the energy came from, what it cost and saved, and a replay tab",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-next-insights-card",preview:!0});const ri=[{key:"next_src_solar",entity:"sensor.sem_solar_power"},{key:"next_src_grid",entity:"sensor.sem_grid_power"},{key:"next_src_battery",entity:"sensor.sem_battery_power"},{key:"next_src_car",entity:"sensor.sem_ev_power"},{key:"next_src_forecast",entity:"sensor.sem_forecast_today_kwh",okS:7200,oldS:28800},{key:"next_src_price",entity:"sensor.sem_tariff_current_import_rate",okS:7200,oldS:93600}];function ai(t,e=Date.now()){const s=Date.parse(t?.last_updated||"");return Number.isFinite(s)?Math.max(0,(e-s)/1e3):null}function ni(t,e=Date.now(),{okS:s=null,oldS:i=null}={}){if(!t)return"missing";const r=t.state;if("unavailable"===r||"unknown"===r||null==r)return"off";if(null===s||null===i)return"ok";const a=ai(t,e);return null===a?"off":a<=s?"ok":a<=i?"old":"off"}function oi(t,e=Date.now()){const s=[];for(const i of ri){const r=t?.[i.entity];if(!r)continue;const a=ni(r,e,{okS:i.okS??null,oldS:i.oldS??null});s.push({key:i.key,entity:i.entity,state:a,age:ai(r,e),value:r.state})}return s}const li={charger:{icon:"mdi:ev-station",color:"#8DC892"},battery:{icon:"mdi:home-battery",color:"#4db6ac"},load:{icon:"mdi:power-plug",color:"#5BC8D8"},export:{icon:"mdi:transmission-tower-export",color:"#8353d1"}},ci=t=>`${t?.device_kind||""}:${t?.device_id||""}`;function di(t,e,s=!1){const i=t?.name;if(i&&i!==t.device_id)return i;const r=e(`why_kind_${t?.device_kind}`);return r&&r!==`why_kind_${t?.device_kind}`?s?`${r} ${t.device_id}`:r:i||t?.device_id||""}function pi(t,e){if(!t)return"";const[s,...i]=String(t).split(" "),r=i.join(" ");if("charge"===s&&r)return r;const a=`why_verb_${s}`,n=e(a),o=n&&n!==a?n:s.replace(/_/g," ");return r?`${o} ${r}`:o}function _i(t,e){const s=t?.reason_code;if(!s)return null;const i=`why_reason_${s}`,r=e(i);if(!r||r===i)return null;const a=t.params||{};let n=!1;const o=String(r).replace(/\{(\w+)\}/g,(t,e)=>{const s=a[e];return null==s||""===s?(n=!0,t):String(s)});return n?null:o}const hi=t=>"number"==typeof t&&Number.isFinite(t)?t:null;function ui(t){const e=hi(t);return null===e?"":Math.abs(e)>=1e3?`${(e/1e3).toFixed(1)} kW`:`${Math.round(e)} W`}const gi=(t,e)=>{try{return t.toLocaleDateString("en-CA",{timeZone:e||void 0})}catch(e){return t.toDateString()}};function mi(t,e=new Date,s){const i=new Date(t);return!Number.isNaN(i.getTime())&&gi(i,s)===gi(e,s)}const fi=["sensor.sem_diag_version","sensor.sem_energy_plan","sensor.sem_target_peak_limit","number.sem_night_start_offset_min","number.sem_night_earliest_start","number.sem_night_latest_end","select.sem_battery_mode","number.sem_battery_buffer_soc","number.sem_battery_priority_soc","number.sem_battery_assist_min_surplus","switch.sem_battery_may_assist_ev","switch.sem_energy_plan_actuation",...ri.map(t=>t.entity)];function yi(t,e,s,i){const r=null!=t?t:i<=1?e??null:null;return null!=r?{soc:r,isEstimate:!1}:null!=s?{soc:s,isEstimate:!0}:{soc:null,isEstimate:!1}}kt("sem-next-system-card",class extends ss{static get styles(){return es}_watchIds(){const t=[];for(const e of this._chargers)t.push(`time.sem_charger_${e}_target_time`,`number.sem_charger_${e}_daily_ev_target`);return[...super._watchIds(),...fi,...t]}_sources(){const t=oi(this._hass.states,Date.now());if(!t.length)return K;const e={ok:"",old:"warn",off:"bad",missing:"off"};return H`<div class="sec"><h3>${this._t("next_sources")}</h3><div class="list">
            ${this._inputsDegraded()?H`<div class="item"><i class="warn"></i>
                <div>${this._t("next_inputs_degraded")}<span>${this._name("sensor.sem_diag_inputs_degraded")}</span></div><b></b></div>`:K}
            ${t.map(t=>{return H`<div class="item"><i class="${e[t.state]||""}"></i>
                <div>${this._t(t.key)}<span>${this._name(t.entity)}${null===t.age?"":" · "+(s=t.age,null!==s&&Number.isFinite(s)?s<90?`${Math.round(s)} s`:s<5400?`${Math.round(s/60)} min`:`${Math.round(s/3600)} h`:"")}</span></div>
                <b>${this._t("next_fresh_"+t.state)}</b></div>`;var s})}
        </div></div>`}_inputsDegraded(){const t=String(this._str("sensor.sem_diag_inputs_degraded")||"").toLowerCase();return"true"===t||"on"===t}_refused(){const t=this._attrs("switch.sem_observer_mode"),e=this._observer(),s=Object.values(t.withheld_commands||{}),i=Object.values(t.would_decisions||{}).filter(t=>t&&t.action&&"idle"!==t.action),r=e?i:s,a=t=>this._t(t);return H`<div class="sec"><h3>${e?this._t("next_would_do"):this._t("next_refused")}</h3>
            ${r.length?H`<div class="list">${r.slice(0,8).map(t=>H`<div class="item"><i class="warn"></i>
                <div>${di(t,a)}${t.action?` · ${t.action}`:""}<span>${_i(t,a)||t.reason||""}</span></div>
                <b class="num">${Number.isFinite(Number(t.power_w))?this._fmtKw(Number(t.power_w))+" kW":""}</b></div>`)}</div>`:H`<div class="hint">${e?this._t("next_would_none"):this._t("next_refused_none")}</div>`}
        </div>`}_numRow(t,e,s,i=1){if(!this._hass.states[t])return K;const r=this._attrs(t);return H`<dt>${this._t(e)}</dt><dd><input type="number" .value=${String(this._num(t)??"")} min="${r.min??0}" max="${r.max??1e3}" step="${r.step??i}" @change=${e=>this._setNumber(t,Number(e.target.value))}> ${s}</dd>`}_settings(){const t=this._hass.states["number.sem_night_start_offset_min"]?"number.sem_night_start_offset_min":null,e=!t&&this._hass.states["number.sem_night_earliest_start"]?"number.sem_night_earliest_start":null,s=this._hass.states["select.sem_battery_mode"]?"select.sem_battery_mode":null,i=this._hass.states["switch.sem_battery_may_assist_ev"]?"switch.sem_battery_may_assist_ev":null,r=this._hass.states["switch.sem_energy_plan_actuation"]?"switch.sem_energy_plan_actuation":null,a=this._num("sensor.sem_target_peak_limit");return H`
            <div class="sec"><h3>${this._t("next_q_car_grid")}</h3><dl class="kv">
                ${t?this._numRow(t,"next_night_offset","min",5):K}
                ${e?this._numRow(e,"next_night_earliest","h",.5):K}
                ${this._numRow("number.sem_night_latest_end","next_night_end","h",.5)}
                ${this._chargers.map(t=>{const e=this._chargerEntity("time",t,"target_time"),s=this._chargerEntity("number",t,"daily_ev_target");return H`
                        ${e?H`<dt>${this._chargerName(t)} · ${this._t("next_charge_by")}</dt><dd><input type="time" .value=${(this._str(e)||"").slice(0,5)} @change=${t=>this._hass.callService("time","set_value",{entity_id:e,time:t.target.value+":00"})}></dd>`:K}
                        ${s?this._numRow(s,"next_at_least","kWh",.5):K}`})}
            </dl><div class="hint">${this._t("next_q_car_grid_hint")}</div></div>
            <div class="sec"><h3>${this._t("next_q_battery")}</h3><dl class="kv">
                ${s?H`<dt>${this._t("next_mode")}</dt><dd><select @change=${t=>this._selectOption(s,t.target.value)}>
                    ${(this._attrs(s).options||[]).map(t=>H`<option value="${t}" ?selected=${t===this._str(s)}>${this._t("battery_mode_"+t)||t}</option>`)}</select></dd>`:K}
                ${this._numRow("number.sem_battery_buffer_soc","next_buffer","%")}
                ${this._numRow("number.sem_battery_priority_soc","next_priority_soc","%")}
                ${this._numRow("number.sem_battery_assist_min_surplus","next_solar_gate","W",50)}
                ${i?H`<dt>${this._t("next_may_feed_car")}</dt><dd><label class="toggle"><input type="checkbox" .checked=${"on"===this._str(i)} @change=${()=>this._toggleSwitch(i)}></label></dd>`:K}
            </dl></div>
            <div class="sec"><h3>${this._t("next_q_limits")}</h3><dl class="kv">
                ${null!==a?H`<dt>${this._t("next_peak_limit")}</dt><dd class="num">${this._fmt(a,1)} kW</dd>`:K}
                ${r?H`<dt>${this._t("next_plan_acts")}</dt><dd><label class="toggle"><input type="checkbox" .checked=${"on"===this._str(r)} @change=${()=>this._toggleSwitch(r)}></label></dd>`:K}
                <dt>${this._t("next_observer")}</dt><dd>${this._observer()?this._t("next_yes"):this._t("next_no")}</dd>
            </dl><a class="btn" href="/sem-dashboard/config">${this._t("next_all_settings")}</a></div>`}render(){if(!this._hass)return K;const t=oi(this._hass.states,Date.now()).filter(t=>"ok"!==t.state).length+(this._inputsDegraded()?1:0),e=this._attrs("sensor.sem_energy_plan"),s=e.computed_at?Math.round((Date.now()-Date.parse(e.computed_at))/6e4):null,i=t?this._tf("next_sys_lead_bad",{n:t}):this._t("next_sys_lead_ok"),r=this._str("sensor.sem_diag_version"),a=[null!==s&&Number.isFinite(s)?this._tf("next_plan_age",{min:s}):"",this._observer()?this._t("next_observer_on"):this._t("next_observer_off"),r?`SEM ${r}`:""].filter(Boolean).join(" · ");return H`<ha-card><div class="wrap">
            ${this._renderHead()}
            ${this._renderLead(i,a)}
            <div class="grid2">
                ${this._sources()}
                ${this._refused()}
                ${this._settings()}
            </div>
        </div></ha-card>`}},{type:"sem-next-system-card",name:"SEM Next · System",description:"Health first: source freshness, what SEM refused, and the settings grouped by question",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-next-system-card",preview:!0});const vi=["now","night_open","ev_charge_start","ev_min_reached","ev_deadline"];const bi=36e5,xi=["ev_charge_start","ev_min_reached","ev_deadline"];function $i(t){const e=String(t?.timestamp||"");return/^\d{4}-\d{2}/.test(e)?e.slice(0,7):""}function wi(t,e){const[s,i]=t.split("-").map(Number),r=12*s+(i-1)+e,a=Math.floor(r/12);return`${a}-${String(r-12*a+1).padStart(2,"0")}`}function ki(t,e){return(t||[]).filter(t=>$i(t)===e)}const Si=t=>{const e=Number(t);return Number.isFinite(e)?e:null};function Ci(t){let e=0,s=0,i=0,r=0,a="",n=0,o=0;for(const l of t||[]){const t=Si(l.energy_kwh)||0;e+=t,s+=t*((Si(l.solar_share_pct)||0)/100);const c=Si(l.cost);null!==c&&""!==l.cost&&void 0!==l.cost&&null!==l.cost&&(i+=c,r+=1),!a&&l.currency&&(a=String(l.currency)),null!==l.co2_kg&&void 0!==l.co2_kg&&""!==l.co2_kg&&null!==Si(l.co2_kg)&&(n+=Si(l.co2_kg),o+=1)}return{count:(t||[]).length,kwh:Math.round(10*e)/10,solarPct:e>0?Math.round(s/e*100):0,cost:r?Math.round(100*i)/100:null,co2:o?Math.round(10*n)/10:null,currency:a}}const zi="sem_config_advanced_v1",Mi="sem-view-mode-changed";function Di(){try{return"1"===localStorage.getItem(zi)}catch(t){return!1}}function Ei(t){try{localStorage.setItem(zi,t?"1":"0")}catch(t){}window.dispatchEvent(new CustomEvent(Mi,{detail:{all:!!t}}))}const Ni="sensor.sem_",Fi=["#8DC892","#64B5F6"];kt("sem-ev-status-card",class extends Lt{static get properties(){return{...super.properties,_showHelp:{state:!0},_sessions:{state:!0},_allSettings:{state:!0},_folds:{state:!0}}}constructor(){super(),this._chargers=[],this._lastStateCount=0,this._showHelp=!1,this._sessions={},this._boundVisibility=()=>{document.hidden||this.requestUpdate()},this._allSettings=!1,this._folds={},this._boundViewMode=t=>this._applyViewMode(t&&t.detail&&"boolean"==typeof t.detail.all?t.detail.all:Di())}connectedCallback(){super.connectedCallback(),document.addEventListener("visibilitychange",this._boundVisibility),this._applyViewMode(Di()),window.addEventListener(Mi,this._boundViewMode)}disconnectedCallback(){super.disconnectedCallback(),this._pauseTimer&&(clearInterval(this._pauseTimer),this._pauseTimer=null),document.removeEventListener("visibilitychange",this._boundVisibility),window.removeEventListener(Mi,this._boundViewMode)}_applyViewMode(t){t!==this._allSettings&&(this._allSettings=t,this._folds={})}_setView(t){Ei(t),this._applyViewMode(t)}_foldOpen(t,e){const s=(this._folds[t]||{})[e];return"boolean"==typeof s?s:this._allSettings}_toggleFold(t,e){this._folds={...this._folds,[t]:{...this._folds[t]||{},[e]:!this._foldOpen(t,e)}}}_renderFold(t,e,s,i){const r=this._foldOpen(t,e);return H`
            <div class="fold fold-${e} ${r?"open":""}">
                <button class="fold-btn" type="button"
                        aria-expanded=${r?"true":"false"}
                        @click=${s=>{s.stopPropagation(),this._toggleFold(t,e)}}>
                    <span class="fold-label">${this._t(s)}</span>
                    <ha-icon icon=${r?"mdi:chevron-up":"mdi:chevron-down"}
                             style="--mdc-icon-size:16px"></ha-icon>
                </button>
                ${r?H`<div class="fold-body">${i}</div>`:K}
            </div>`}_sessionState(t){return this._sessions[t]||{open:!1,loading:!1,rows:null,month:null,all:!1}}_setSessionState(t,e){this._sessions={...this._sessions,[t]:{...this._sessionState(t),...e}}}_toggleSessions(t){const e=this._sessionState(t);this._setSessionState(t,{open:!e.open})}_watchSessions(t,e){this._sessWatch||(this._sessWatch={});for(const s of this._chargers){const i=t.states[`binary_sensor.sem_charger_${s}_connected`]?.state||"",r=parseFloat(t.states[`${e}charger_${s}_session_energy`]?.state)||0,a=this._sessWatch[s];this._sessWatch[s]={conn:i,sess:r};const n=a&&("on"===a.conn&&"off"===i||a.sess>0&&0===r);a&&!n||this._loadSessions(s)}}async _loadSessions(t){if(this._sessionState(t).loading||!this._hass?.callWS)return;this._setSessionState(t,{loading:!0});let e=[];try{const s=await this._hass.callWS({type:"solar_energy_management/session_history",charger_id:t});e=Array.isArray(s?.rows)?s.rows:[]}catch(t){e=[]}const s=new Date,i=`${s.getFullYear()}-${String(s.getMonth()+1).padStart(2,"0")}`,r=this._sessionState(t).month;this._setSessionState(t,{loading:!1,rows:e,month:r||i})}async _downloadSessionsXlsx(t){if(this._hass?.callWS)try{const e=await this._hass.callWS({type:"solar_energy_management/session_history/xlsx",charger_id:t});e?.base64&&(ys(e.filename||"sem-sessions.xlsx",e.base64,"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),this._setSessionState(t,{error:null}))}catch(e){console.warn("SEM: session download failed",e),this._setSessionState(t,{error:"download"})}}_renderSessions(t){const e=this._sessionState(t),s=this._hass?.language||"en",i=(t,e)=>(this._t(t)||"").split("{n}").join(String(e)),r=e.rows||[],a=new Date,n=`${a.getFullYear()}-${String(a.getMonth()+1).padStart(2,"0")}`,o=Ci(ki(r,n)),l=e.rows?i("sessions_this_month",o.count)+" · "+o.kwh.toFixed(1)+" kWh":"",c=e.month||n,d=ki(r,c),p=Ci(d),_=e.all?d:d.slice(0,6),h=d.length-_.length,u=p.currency||ft(this._hass)||"";let g=c;try{g=new Date(c+"-15T12:00:00Z").toLocaleDateString(s,{month:"long",year:"numeric",timeZone:"UTC"})}catch(t){}const m=r.length?$i(r[r.length-1]):c,f=c>m,y=c<n,v="display:grid;grid-template-columns:2.1fr .7fr .7fr .7fr .7fr .5fr;gap:6px;align-items:center;font-variant-numeric:tabular-nums;";return H`
            <div class="sessions-block">
                <div class="strip-title sessions-head" @click=${()=>this._toggleSessions(t)}>
                    <span class="sessions-name">
                        <ha-icon icon="mdi:history" style="--mdc-icon-size:13px;color:#8DC892"></ha-icon>
                        <span>${this._t("sessions_title")}</span>
                    </span>
                    <span class="metric-label">${l} ${e.open?"▴":"▾"}</span>
                </div>
                ${e.open?e.rows?H`
                    <div class="metric-row sessions-month">
                        <span class="metric-value sessions-nav">
                            <span class="nav ${f?"":"off"}"
                                  @click=${()=>f&&this._setSessionState(t,{month:wi(c,-1),all:!1})}>‹</span>
                            ${g}
                            <span class="nav ${y?"":"off"}"
                                  @click=${()=>y&&this._setSessionState(t,{month:wi(c,1),all:!1})}>›</span>
                        </span>
                        <span class="metric-label">${p.kwh.toFixed(1)} kWh · ${p.solarPct} % ${this._t("sessions_solar_word")}${null===p.cost?"":" · "+p.cost.toFixed(2)+" "+u}${null===p.co2?"":" · "+p.co2.toFixed(1)+" kg CO₂"}</span>
                    </div>
                    ${0===d.length?H`
                        <div class="metric-label sessions-note">${this._t("sessions_none")}</div>`:H`
                        <div class="ct-row" style="${v}min-height:24px">
                            <span class="metric-label">${this._t("sessions_col_session")}</span>
                            <span class="metric-label num">kWh</span>
                            <span class="metric-label num">${this._t("sessions_col_solar")}</span>
                            <span class="metric-label num">${u}</span>
                            <span class="metric-label num">${this._t("sessions_col_co2")}</span>
                            <span class="metric-label num">${this._t("sessions_col_min")}</span>
                        </div>
                        ${_.map(t=>{const e=function(t,e="en"){const s=String(t?.timestamp||""),i=String(t?.end||""),r=s.slice(0,10);let a="";if(/^\d{4}-\d{2}-\d{2}$/.test(r)){const t=new Date(`${r}T12:00:00Z`);let s="";try{s=t.toLocaleDateString(e||"en",{weekday:"short",timeZone:"UTC"})}catch(e){s=t.toLocaleDateString("en",{weekday:"short",timeZone:"UTC"})}a=`${s} ${r.slice(8,10)}.${r.slice(5,7)}`}const n=s.length>=16?s.slice(11,16):"",o=i.length>=16?i.slice(11,16):"",l=Si(t?.solar_share_pct),c=null==t?.cost||""===t?.cost?null:Si(t.cost),d=null==t?.co2_kg||""===t?.co2_kg?null:Si(t.co2_kg),p=Si(t?.duration_min),_=Si(t?.energy_kwh);return{day:a,span:n&&o?`${n}–${o}`:n,kwh:null===_?"":_.toFixed(1),solar:null===l?"":`${Math.round(l)}%`,solarHigh:null!==l&&Math.round(l)>=80,cost:null===c?"":c.toFixed(2),co2:null===d?"":d.toFixed(1),min:null===p?"":String(Math.round(p))}}(t,s);return H`
                                <div class="ct-row" style="${v}">
                                    <span class="metric-value sessions-day">${e.day} <span class="metric-label sessions-span">${e.span}</span></span>
                                    <span class="metric-value num">${e.kwh}</span>
                                    <span class="metric-value num" style="color:${e.solarHigh?"#ff9800":"var(--primary-text-color, #e0e0e0)"}">${e.solar}</span>
                                    <span class="metric-value num">${e.cost}</span>
                                    <span class="metric-value num">${e.co2}</span>
                                    <span class="metric-value num" style="font-weight:500">${e.min}</span>
                                </div>`})}`}
                    <div class="ct-row sessions-foot">
                        <span class="metric-label ${h>0?"clickable":""}"
                              @click=${()=>h>0&&this._setSessionState(t,{all:!0})}>${h>0?i("sessions_more",h)+" · ":""}${i("sessions_stored",r.length)}</span>
                        ${r.length?H`
                            <span class="metric-value sessions-dl" @click=${()=>this._downloadSessionsXlsx(t)}>
                                <ha-icon icon="mdi:download" style="--mdc-icon-size:14px"></ha-icon>${this._t("sessions_xlsx")}
                            </span>
                            ${"download"===e.error?H`<span class="metric-label">${this._t("sessions_download_failed")}</span>`:K}`:K}
                    </div>`:H`
                    <div class="metric-label sessions-note">${this._t("sessions_loading")}</div>`:K}
            </div>
        `}_toggleHelp(){this._showHelp=!this._showHelp}set hass(t){this._hass,this._hass=t;const e=t?.language,s="function"==typeof semLocalize;let i=!1;if((e!==this._lang||s&&!this._localizeReady)&&(this._lang=e,this._localizeReady=s,i=!0),this._isFrozen()&&!i)return;const r=Object.keys(t.states).length;if(r!==this._lastStateCount){this._lastStateCount=r;const e=[];for(const s of Object.keys(t.states)){if(s.includes("_flow_"))continue;const t=s.match(/^sensor\.sem_charger_(.+)_power$/);t&&e.push(t[1])}this._chargers=e}const a=this._config?.entity_prefix||Ni;this._watchSessions(t,a);let n=["ev_connected","ev_charging","ev_power","calculated_current","session_energy","session_solar_share","session_cost","daily_ev_energy","energy_ev_solar_percentage","charging_state"].map(e=>{const s="ev_connected"===e||"ev_charging"===e?"binary_sensor.sem_":a;return t.states[`${s}${e}`]?.state||""}).join(",");if(this._chargers.length>=1){n+="|"+this._chargers.map(e=>[`charger_${e}_power`,`charger_${e}_session_energy`,`charger_${e}_session_energy_external`,`charger_${e}_daily_energy`,`charger_${e}_session_solar_share`,`charger_${e}_estimated_soc`,`charger_${e}_vehicle_soc`,`charger_${e}_commanded_current`].map(e=>t.states[`${a}${e}`]?.state||"").join(":")).join("|"),n+="|"+this._chargers.map(e=>t.states[`time.sem_charger_${e}_target_time`]?.state||"").join(":");const e=t.states[`${a}charging_state`]?.attributes||{};n+="|"+[e.ev_tariff_waiting,e.ev_deadline_reachable,e.ev_next_cheap_window].join(":"),n+="|"+this._chargers.map(t=>!0===((e.per_charger_stop_war||{})[t]||{}).standing_down?"1":"0").join(":"),n+="|"+JSON.stringify([e.per_charger_departure||{},e.battery_boost||null,Math.round(Number(e.battery_soc)||0)]),n+="|"+this._chargers.map(e=>t.states[`number.sem_charger_${e}_daily_ev_target`]?.state||"").join(":"),n+="|"+this._chargers.map(e=>[t.states[`select.sem_charger_${e}_ev_target_type`]?.state||"",t.states[`number.sem_charger_${e}_target_soc`]?.state||"",t.states[`number.sem_charger_${e}_daily_ev_target_max`]?.state||"",t.states[`number.sem_charger_${e}_target_soc_max`]?.state||"",t.states[`number.sem_charger_${e}_ev_battery_capacity_kwh`]?.state||"",t.states[`number.sem_charger_${e}_ev_kwh_per_100km`]?.state||""].join(":")).join("|"),n+="|"+(t.states[`${a}ev_remaining_range`]?.state||"")}n+="|"+this._localizeReady+"|"+this._lang,(n!==this._lastKey||i)&&(this._lastKey=n,this._scheduleUpdate())}get hass(){return this._hass}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||Ni}_binaryState(t){const e=this._hass?.states[`binary_sensor.sem_${t}`];return"on"===e?.state}_val(t,e=null){return At(this._hass?.states[`${this._prefix}${t}`])??e}_valStr(t){const e=this._hass?.states[`${this._prefix}${t}`];return e?.state||""}_entityVal(t,e=null){const s=this._frozenEntities[t];return s?s.value:At(this._hass?.states[t])??e}_fmt(t,e=1){return null==t||isNaN(t)?"—":t.toFixed(e)}_chargerName(t){const e=this._hass?.states[`${this._prefix}charger_${t}_power`];let s=t.replace(/_/g," ").replace(/\b\w/g,t=>t.toUpperCase());return e?.attributes?.charger_name?e.attributes.charger_name:(e?.attributes?.friendly_name&&(s=e.attributes.friendly_name.replace(/^SEM\s+/i,"").replace(/\s+Power$/i,"")),s)}_renderSocGauge(t,e=!1){const s=null!=t?Math.max(0,Math.min(100,t)):0,i=s>60?"#8DC892":s>30?"#ff9800":"#f06292",r=Math.max(2,s/100*52);return H`
            <svg viewBox="0 0 44 76" width="44" height="76">
                <rect x="14" y="0" width="16" height="5" rx="2" fill="rgba(255,255,255,0.15)"/>
                <rect x="6" y="4" width="32" height="60" rx="4"
                    fill="none" stroke="rgba(255,255,255,0.15)" stroke-width="2"/>
                <rect x="9" y="${52-r+7}" width="26" height="${r}" rx="2"
                    fill="${i}" opacity="0.7"/>
                <text x="22" y="40" text-anchor="middle"
                    fill="white" font-size="14" font-weight="700"
                    font-family="'Segoe UI','Roboto',sans-serif"
                    opacity="0.95">
                    ${null!=t?(e?"~":"")+Math.round(t)+"%":"—"}
                </text>
            </svg>
        `}updated(t){super.updated?.(t);const e=Object.keys(this._hass?.states||{}).some(t=>t.startsWith("select.sem_charger_")&&t.endsWith("_charge_mode")&&"off"===this._hass.states[t]?.state&&this._hass.states[t]?.attributes?.paused_until);e&&!this._pauseTimer?this._pauseTimer=setInterval(()=>this.requestUpdate(),6e4):!e&&this._pauseTimer&&(clearInterval(this._pauseTimer),this._pauseTimer=null)}_departureFor(t,e){const s={...((e||{}).per_charger_departure||{})[t]||{}},i=(this._depPending||{})[t];return i&&Date.now()-i.at<2e4&&Object.assign(s,i.values),s}_writeDeparture(t,e){const s=((this._depPending||{})[t]||{}).values||{};this._depPending={...this._depPending||{},[t]:{at:Date.now(),values:{...s,...e}}},this.requestUpdate();const i={charger_id:t};"by_weekday"in e&&(i.by_weekday=e.by_weekday),"one_block"in e&&(i.one_block=e.one_block),"late_min"in e&&(i.late_charge_min=e.late_min),this._callService("solar_energy_management","set_charger_departure",i)}_fmtT(t,e){let s=this._t(t)||"";for(const[t,i]of Object.entries(e||{}))s=s.split(`{${t}}`).join(String(i));return s}_hhmm(t){return t.toLocaleTimeString([],{hour:"2-digit",minute:"2-digit",timeZone:this._hass?.config?.time_zone||void 0})}_dayName(t,e){const s=["mon","tue","wed","thu","fri","sat","sun"];try{return new Intl.DateTimeFormat(this._hass?.language||"en",{weekday:e,timeZone:"UTC"}).format(new Date(Date.UTC(2024,0,1+t,12)))}catch(e){return s[t]}}_nextDeparture(t){const e=["mon","tue","wed","thu","fri","sat","sun"],s=t.next?new Date(t.next):null;if(!s||isNaN(s))return{next:null,key:null,label:""};let i=null;try{i=new Intl.DateTimeFormat("en-US",{weekday:"short",timeZone:this._hass?.config?.time_zone||void 0}).format(s).toLowerCase().slice(0,3)}catch(t){i=null}return{next:s,key:i,label:e.includes(i)?`${this._dayName(e.indexOf(i),"short")} ${this._hhmm(s)}`:this._hhmm(s)}}_renderDepartureRows(t,e,s){const i=["mon","tue","wed","thu","fri","sat","sun"],r=e.by_weekday||{},a=(t,e)=>this._dayName(t,e),{next:n,key:o}=this._nextDeparture(e),l=!!n,c=this._depEdit&&this._depEdit.id===t?this._depEdit.day:null,d=(e,i)=>{const a={...r};i&&i!==s?a[e]=i:delete a[e],this._writeDeparture(t,{by_weekday:a})},p=e=>{this._depEdit=c===e?null:{id:t,day:e},this.requestUpdate()},_=!!e.one_block,h=[0,15,30,45,60,90,120],u=Number(e.late_min)||0,g=h.includes(u)?h:[...h,u].sort((t,e)=>t-e);let m="";if(u>0&&l){const t=e.late||null,s=t&&t.start?new Date(t.start):new Date(n.getTime()-6e4*u),i=t&&t.end?new Date(t.end):n;if(!isNaN(s)&&!isNaN(i)){const e=`${this._hhmm(s)}–${this._hhmm(i)}`;m=t?this._fmtT("ev_dep_late_hint_plan",{span:e,kwh:Number(t.kwh||0).toFixed(1),cost:`${Number(t.cost||0).toFixed(2)} ${ft(this._hass)}`}):this._fmtT("ev_dep_late_hint",{span:e})}}const f=t=>this._showHelp?H`
            <div class="ct-subhint dep-hint">
                <div class="ct-hint-row"><span class="ct-hint-text">${this._t(t)}</span></div>
            </div>`:K;return H`
            <div class="dep-days">
                ${i.map((t,e)=>H`
                    <button class="dep-day ${r[t]?"own":""} ${t===o?"next":""} ${t===c?"open":""}"
                            title=${a(e,"long")}
                            @click=${e=>{e.stopPropagation(),p(t)}}>
                        <span class="d">${a(e,"short")}</span>
                        <span class="t">${r[t]||s}</span>
                    </button>`)}
            </div>
            ${c?H`
            <div class="ct-row dep-edit">
                <span class="ct-label">${a(i.indexOf(c),"long")}</span>
                <span class="ct-ctl">
                    <input type="time" class="dep-time-input"
                           .value=${r[c]||s}
                           @click=${t=>t.stopPropagation()}
                           @change=${t=>d(c,t.target.value)}>
                    ${r[c]?H`
                    <button class="dep-clear"
                            @click=${t=>{t.stopPropagation(),d(c,"")}}>
                        ${this._fmtT("ev_dep_use_default",{time:s})}
                    </button>`:K}
                </span>
            </div>`:K}
            <div class="ct-subhint dep-hint">
                <div class="ct-hint-row">
                    <span class="ct-hint-text">${this._fmtT("ev_dep_tap_hint",{time:s})}</span>
                </div>
            </div>
            ${f("ev_dep_help_days")}
            <div class="ct-row">
                <span class="ct-label">${this._t("ev_dep_one_block")}</span>
                <span class="ct-ctl">
                    <span class="ct-sw ${_?"on":"off"}" role="switch"
                          aria-checked=${_?"true":"false"}
                          @click=${e=>{e.stopPropagation(),this._writeDeparture(t,{one_block:!_})}}>
                        <span class="ct-knob"></span>
                    </span>
                </span>
            </div>
            ${f("ev_dep_help_one_block")}
            <div class="ct-row">
                <span class="ct-label">${this._t("ev_dep_late_charge")}</span>
                <span class="ct-ctl">
                    <select class="ct-mode-select" .value=${String(u)}
                            @click=${t=>t.stopPropagation()}
                            @change=${e=>this._writeDeparture(t,{late_min:Number(e.target.value)})}>
                        ${g.map(t=>H`
                            <option value=${String(t)} ?selected=${t===u}>
                                ${t?this._fmtT("ev_dep_minutes",{n:t}):this._t("ev_dep_late_off")}
                            </option>`)}
                    </select>
                </span>
            </div>
            ${m?H`
            <div class="ct-subhint dep-hint">
                <div class="ct-hint-row"><span class="ct-hint-text">${m}</span></div>
            </div>`:K}
            ${f("ev_dep_help_late")}
        `}_renderBoostRow(t,e,s){if(!("sensor.sem_battery_soc"in(this._hass?.states||{})))return K;const i=s.battery_boost||null,r=s.battery_boost_preview||{},a=!(!i||!i.active||i.charger_id!==t),n=!1!==e.boost_allowed,o=Math.round(Number(r.default_floor??50)),l=(this._boostFloor||{})[t],c=null!=l?l:o,d=[10,20,30,40,50,60,70,80,90],p=d.includes(c)?d:[...d,c].sort((t,e)=>t-e),_=Number(s.battery_soc),h=Number.isFinite(_),u=Number(r.capacity_kwh)||0,g=this._boostError&&this._boostError.id===t?this._boostError.message:null,m=this._showHelp?H`
            <div class="ct-subhint boost-hint">
                <div class="ct-hint-row"><span class="ct-hint-text">${this._t("ev_boost_help")}</span></div>
            </div>`:K;if(a){const t=Math.round(Number(i.floor_soc)),e=Number(i.start_soc),s=Number.isFinite(Number(i.soc))?Number(i.soc):_,r=Number.isFinite(e)&&Number.isFinite(s)&&e>t?Math.max(0,Math.min(100,(e-s)/(e-t)*100)):null;return H`
                <div class="ct-row boost-row">
                    <span class="ct-label">${this._t("ev_boost_title")}</span>
                    <span class="ct-ctl">
                        <span class="ct-time boost-floor">${this._fmtT("ev_boost_down_to",{floor:t})}</span>
                        <button class="ct-boost-btn stop"
                                @click=${t=>{t.stopPropagation(),this._callService("solar_energy_management","stop_battery_boost",{})}}>
                            <ha-icon icon="mdi:stop" style="--mdc-icon-size:14px"></ha-icon>
                            ${this._t("ev_boost_stop")}
                        </button>
                    </span>
                </div>
                <div class="ct-subhint boost-hint">
                    <div class="ct-hint-row"><span class="ct-hint-text">${this._fmtT("ev_boost_left",{kwh:Number(i.remaining_kwh||0).toFixed(1),soc:Number.isFinite(s)?Math.round(s):"—",floor:t})}</span></div>
                    ${null!=r?H`<div class="boost-bar"><i style="width:${r.toFixed(0)}%"></i></div>`:K}
                    <div class="ct-hint-row"><span class="ct-hint-text">${this._fmtT("ev_boost_ends",{floor:t})}</span></div>
                </div>
                ${m}
            `}const f=h&&u>0?Math.max(0,(_-c)/100*u):null,y=i&&!i.active&&i.last_end&&i.last_end.charger_id===t?i.last_end:null,v=y?new Date(y.at):null,b=!!(v&&!isNaN(v)&&Date.now()-v.getTime()<432e5);let x=K;if(n)if(g)x=H`
                <div class="ct-warn">
                    <ha-icon icon="mdi:alert-circle-outline" style="--mdc-icon-size:14px;color:#f06292"></ha-icon>
                    <span>${g}</span>
                </div>`;else if(b){const t={unplugged:"ev_boost_end_unplugged","mode changed":"ev_boost_end_mode_changed","permission off":"ev_boost_end_permission_off","battery at its floor":"ev_boost_end_floor",stopped:"ev_boost_end_stopped","charger removed":"ev_boost_end_charger_removed"}[y.reason];x=H`
                <div class="ct-subhint boost-hint">
                    <div class="ct-hint-row"><span class="ct-hint-text">${this._fmtT("ev_boost_last_end",{time:this._hhmm(v),reason:t?this._t(t):y.reason})}</span></div>
                </div>`}else x=H`
                <div class="ct-subhint boost-hint">
                    <div class="ct-hint-row"><span class="ct-hint-text">${this._fmtT("ev_boost_hint",{soc:h?Math.round(_):"—",kwh:null!=f?f.toFixed(1):"—"})}</span></div>
                </div>`;else x=H`
                <div class="ct-warn">
                    <ha-icon icon="mdi:battery-lock" style="--mdc-icon-size:14px;color:#f06292"></ha-icon>
                    <span>${this._t("ev_boost_not_permitted")}</span>
                </div>`;return H`
            <div class="ct-row boost-row">
                <span class="ct-label">${this._t("ev_boost_title")}</span>
                <span class="ct-ctl">
                    <select class="ct-mode-select" .value=${String(c)}
                            @click=${t=>t.stopPropagation()}
                            @change=${e=>{this._boostFloor={...this._boostFloor||{},[t]:Number(e.target.value)},this.requestUpdate()}}>
                        ${p.map(t=>H`
                            <option value=${String(t)} ?selected=${t===c}>
                                ${this._fmtT("ev_boost_down_to",{floor:t})}
                            </option>`)}
                    </select>
                    <button class="ct-boost-btn" ?disabled=${!n}
                            @click=${e=>{e.stopPropagation(),this._startBoost(t,c)}}>
                        <ha-icon icon="mdi:home-battery-outline" style="--mdc-icon-size:14px"></ha-icon>
                        ${this._t("ev_boost_start")}
                    </button>
                </span>
            </div>
            ${x}
            ${m}
        `}async _startBoost(t,e){if(this._hass){this._boostError=null;try{await this._hass.callService("solar_energy_management","start_battery_boost",{charger_id:t,floor_soc:e})}catch(e){this._boostError={id:t,message:e&&e.message||String(e)}}this.requestUpdate()}}_renderPlanStrip(t){const e=this._hass?.states["sensor.sem_charging_state"],s=t?e?.attributes?.per_charger_plans?.[t]:null,i=Array.isArray(s)&&s.length>0?s:e?.attributes?.today_plan||[];if(!Array.isArray(i)||i.length<2)return K;const r=new Set(["ev_charge_start","ev_min_reached","ev_deadline"]);if(!i.some(t=>r.has(t.kind)))return K;const a=Date.now(),n=i.filter(t=>["now","night_open","ev_charge_start","ev_min_reached","ev_deadline"].includes(t.kind));n.sort((t,e)=>new Date(t.when)-new Date(e.when));const{end:o,hours:l}=function(t,e){const s=e+432e5,i=e+864e5;let r=0;for(const e of t||[]){if(!e||!xi.includes(e.kind))continue;const t=new Date(e.when).getTime();Number.isFinite(t)&&t>r&&(r=t)}const a=r>e?Math.ceil((r+1)/bi)*bi:0,n=Math.min(i,Math.max(s,a));return{end:n,hours:Math.max(1,Math.round((n-e)/bi))}}(n,a),c=o-a,d=t=>Math.max(0,Math.min(100,(t-a)/c*100)),p=function(t,{now:e,end:s}){const i=(t||[]).filter(t=>t&&vi.includes(t.kind)).map(t=>({...t,t:new Date(t.when).getTime()})).filter(t=>Number.isFinite(t.t)).sort((t,e)=>t.t-e.t),r=i.filter(t=>"ev_charge_start"===t.kind),a=t=>"plan_ev_charge_estimate"===t.detail?"estimate":"plan_ev_charge_late"===t.detail?"late":"charging",n=[];let o=e,l="idle",c=null;const d=()=>{const t=Math.min(c,s);t>o&&n.push({s:o,e:t,state:l}),o=Math.max(o,t),l="wait",c=null};for(const t of i){null!=c&&c<t.t&&d();const e=Math.min(t.t,s);if(e>o&&n.push({s:o,e:e,state:l}),o=Math.max(o,e),"night_open"===t.kind){const e=r.find(e=>Math.abs(e.t-t.t)<=6e4);l=e?a(e):"wait"}else if("ev_charge_start"===t.kind){l=a(t);const e=t.until?new Date(t.until).getTime():NaN;c=Number.isFinite(e)&&e>t.t?e:null}else"ev_min_reached"!==t.kind&&"ev_deadline"!==t.kind||(l="done",c=null)}return null!=c&&c<s&&d(),o<s&&n.push({s:o,e:s,state:l}),n}(n,{now:a,end:o,fleetTariffWait:!!e?.attributes?.ev_tariff_waiting}),_=[];for(const t of i){const e=new Date(t.when).getTime();if("expensive_start"===t.kind&&e<o){const s=t.values?.end;if(s){const[t,i]=s.split(":").map(Number),r=new Date(e);r.setHours(t,i,0,0),r.getTime()<e&&r.setDate(r.getDate()+1),_.push({s:e,e:Math.min(r.getTime(),o),kind:"expensive"})}}else if("cheap_start"===t.kind&&e<o){const s=t.values?.end;if(s){const[t,i]=s.split(":").map(Number),r=new Date(e);r.setHours(t,i,0,0),r.getTime()<e&&r.setDate(r.getDate()+1),_.push({s:e,e:Math.min(r.getTime(),o),kind:"cheap"})}}}const h=`sem-late-${String(t||"fleet").replace(/[^A-Za-z0-9_-]/g,"_")}`,u=t=>({idle:"#566072",wait:"#8353d1",estimate:"#b8a6e8",charging:"#8DC892",done:"#4db6ac",late:"#5BC8D8"}[t]||"#566072"),g=p.some(t=>"late"===t.state),m=t=>"cheap"===t?"#43a047":"#f06292",f=t=>(this._t(t)||"").split("{hours}").join(l),y=this._hass?.config?.time_zone||void 0,v=[];for(let t=0;t<=4;t++){const e=a+c*t/4,s=new Date(e).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit",timeZone:y});v.push({x:d(e),label:s})}return H`
            <div class="plan-strip" title="${this._t("today_plan_title")} (${l}h)">
                <div class="strip-title">
                    <ha-icon icon="mdi:chart-timeline" style="--mdc-icon-size:13px;color:#5BC8D8"></ha-icon>
                    <span>${f("plan_strip_title")}</span>
                </div>
                <svg viewBox="0 0 ${100} 16" preserveAspectRatio="none" class="strip-svg">
                    ${g?j`
                        <defs>
                            <pattern id="${h}" patternUnits="userSpaceOnUse"
                                     width="1.6" height="16" patternTransform="skewX(-14)">
                                <rect x="0" y="0" width="1.6" height="16" fill="#5BC8D8" />
                                <rect x="0" y="0" width="0.8" height="16" fill="#3d97a3" />
                            </pattern>
                        </defs>`:K}
                    ${p.map(t=>j`
                        <rect x="${d(t.s)}" y="5" width="${d(t.e)-d(t.s)}"
                              height="10" fill="${"late"===t.state?`url(#${h})`:u(t.state)}" />
                    `)}
                    ${_.map(t=>j`
                        <rect x="${d(t.s)}" y="0" width="${d(t.e)-d(t.s)}"
                              height="3" fill="${m(t.kind)}"
                              opacity="0.75" />
                    `)}
                </svg>
                <div class="strip-axis">
                    ${v.map(t=>H`
                        <span class="tick" style="left: ${t.x}%">${t.label}</span>
                    `)}
                </div>
                <div class="strip-legend">
                    <span><i style="background:${u("idle")}"></i>${this._t("plan_strip_idle")}</span>
                    <span><i style="background:${u("wait")}"></i>${this._t("plan_strip_wait")}</span>
                    <span><i style="background:${u("estimate")}"></i>${this._t("plan_strip_estimate")}</span>
                    <span><i style="background:${u("charging")}"></i>${this._t("plan_strip_charging")}</span>
                    <span><i style="background:${u("done")}"></i>${this._t("plan_strip_done")}</span>
                    ${g?H`<span><i class="hatch"></i>${this._t("plan_strip_late")}</span>`:K}
                    <span><i class="line" style="background:${m("cheap")}"></i>${this._t("plan_strip_cheap")}</span>
                    <span><i class="line" style="background:${m("expensive")}"></i>${this._t("plan_strip_expensive")}</span>
                </div>
                ${this._showHelp?H`
                    <div class="setting-help strip-help">${f("plan_strip_help")}</div>
                `:K}
            </div>
        `}_renderRangeSlider(t,e,s){const i=this._hass?.states[t],r=this._hass?.states[e],a=s?"%":" kWh",n=t=>s?String(Math.round(t)):this._fmt(t,t%1==0?0:1);if(!i||!r){const e=this._entityVal(t,s?80:10);return H`<div class="ct-row">
                <span class="ct-label">${this._t("charge_to")}</span>
                <span class="ct-ctl"><span class="ct-val clickable"
                    @click=${()=>this.dispatchEvent(new CustomEvent("hass-more-info",{bubbles:!0,composed:!0,detail:{entityId:t}}))}
                >${n(e)}${a}</span></span></div>`}const o=Math.min(parseFloat(i.attributes.min??0),parseFloat(r.attributes.min??0)),l=Math.max(parseFloat(i.attributes.max??100),parseFloat(r.attributes.max??100)),c=l-o||1;let d=this._entityVal(t,s?80:10),p=this._entityVal(e,100);p<d&&(p=d);const _=(d-o)/c*100,h=(p-o)/c*100,u=p>=l-1e-6,g=parseFloat(this._hass?.states[t]?.attributes?.step)||(l>50?1:5),m=Math.max(g,.02*(l-o)),f=p-d<m-1e-6;return H`
            <div class="range-wrap">
                <div class="range-labels">
                    <span>${this._t("at_least")} <b style="color:#8DC892">${n(d)}${a}</b></span>
                    <span>${this._t("up_to")} <b style="color:#ff9800">${u?this._t("full"):n(p)+a}</b></span>
                </div>
                <div class="range-track">
                    <div class="range-fill" style="left:${_}%;width:${Math.max(0,h-_)}%"></div>
                    <div class="range-handle range-handle-min" style="left:${_}%"
                        @pointerdown=${s=>this._rangeHandleStart(s,"min",t,e,o,l)}></div>
                    <div class="range-handle range-handle-max" style="left:${h}%"
                        @pointerdown=${s=>this._rangeHandleStart(s,"max",t,e,o,l)}></div>
                    ${f?H`
                        <span class="range-split"
                              style="left:${_}%"
                              title="${this._t("separate_handles")}"
                              @click=${s=>{s.stopPropagation();const i=p-m;i>=o?this._setNumber(t,i):this._setNumber(e,Math.min(l,d+m))}}>
                            <ha-icon icon="mdi:arrow-split-vertical"
                                     style="--mdc-icon-size:14px"></ha-icon>
                        </span>
                    `:K}
                </div>
            </div>`}_rangeHandleStart(t,e,s,i,r,a){t.stopPropagation(),t.preventDefault();const n=t.currentTarget.closest(".range-track");if(!n)return;const o="min"===e?s:i,l="min"===e?i:s,c=this._hass?.states[o],d=parseFloat(c?.attributes?.step)||(a>50?1:.5),p=a-r||1,_=t=>{const s=n.getBoundingClientRect();let i=(t-s.left)/(s.width||1);i=Math.max(0,Math.min(1,i));let o=Math.round((r+i*p)/d)*d;const c=this._entityVal(l,"min"===e?a:r);return o="min"===e?Math.min(o,c):Math.max(o,c),Math.max(r,Math.min(a,o))},h=t=>{this._freezeEntity(o,_(t.clientX)),this.requestUpdate()},u=t=>{window.removeEventListener("pointermove",h),window.removeEventListener("pointerup",u),window.removeEventListener("pointercancel",u),this._setNumber(o,_(t.clientX))};window.addEventListener("pointermove",h),window.addEventListener("pointerup",u),window.addEventListener("pointercancel",u)}_renderChargerSection(t,e){const s=Fi[e%Fi.length],i=this._val(`charger_${t}_power`),r=this._val(`charger_${t}_session_energy_external`),a=this._val(`charger_${t}_session_energy`),n=r>0?r:a,o=this._val(`charger_${t}_daily_energy`),l=this._val("energy_ev_solar_percentage"),{soc:c,isEstimate:d}=yi(this._val(`charger_${t}_vehicle_soc`,null),this._val("vehicle_soc",null),this._val(`charger_${t}_estimated_soc`,null),this._chargers.length),p=this._stateAttrs(`sensor.sem_charger_${t}_estimated_soc`),_=p.energy_accounted_soc,h=!0===p.estimate_stop_active,u=this._val(`charger_${t}_vehicle_soc`,null),g=p.vehicle_soc_last??u;let m=null;const f=Date.parse(p.vehicle_soc_last_at??"");Number.isNaN(f)||(m=Math.round((Date.now()-f)/6e4));const y=t=>(this._t(t)||"").replace(/\{soc\}/g,null!=g?Math.round(g):"—").replace(/\{age\}/g,null!=m?m:"—").replace(/\{est\}/g,null!=_?Math.round(_):"—"),v=null!=g&&null!=_&&null!=m&&m>=5&&(_-g>=1||null==u),b=this._chargerName(t),x=this._hass?.states[`binary_sensor.sem_charger_${t}_connected`],$="on"===x?.state,w=i>50,k=(this._stateAttrs(`${this._prefix}charging_state`).per_charger_stop_war||{})[t],S=this._t(function({isCharging:t,isConnected:e,standDown:s}){return t&&s&&!0===s.standing_down?"charger_status_stood_down":t?"charging":e?"connected":"idle"}({isCharging:w,isConnected:$,standDown:k})),C=this._val(`charger_${t}_commanded_current`,0),z=this._entityVal(`number.sem_charger_${t}_minimum_current`,6),M=this._entityVal(`number.sem_charger_${t}_ev_battery_capacity_kwh`,40),D=this._entityVal(`number.sem_charger_${t}_ev_kwh_per_100km`,18),E="select.sem_pause_duration",N=this._stateAttrs(E),F=this._stateStr(E)||"1_hour",A=N.options||[],T=`button.sem_charger_${t}_pause_charging`,I=!!this._hass?.states?.[T],R=`select.sem_charger_${t}_charge_mode`,B=this._stateAttrs(R),O=this._stateStr(R)||"min_plus_solar",L="off"===O?B.paused_until:null,P=L?new Date(L):null,U=!(!P||isNaN(P)),W=U?Math.max(0,Math.round((P-Date.now())/6e4)):0,j=B.pause_resume_mode||"",G=U?P.toLocaleTimeString([],{hour:"2-digit",minute:"2-digit",timeZone:this._hass?.config?.time_zone||void 0}):"",q=W>=60?`${Math.floor(W/60)} h ${W%60} min`:`${W} min`,V=B.options||["solar_only","solar_plus_battery","solar_plus_cheap","min_plus_solar","always_max","off"],Y=!1!==B.tariff_available,Z=B.modes_needing_tariff||[],X=t=>!Y&&Z.includes(t),J=this._stateAttrs("sensor.sem_battery_spendable_kwh"),Q="learning"===J.phase,tt=(this._t("charge_mode_battery_learning_info")||"").replace(/\{n\}/g,J.nights_sealed??"?").replace(/\{total\}/g,J.nights_required??"?"),et={solar_only:this._t("charge_mode_solar_only"),solar_plus_battery:this._t("charge_mode_solar_plus_battery"),solar_plus_cheap:this._t("charge_mode_solar_plus_cheap"),min_plus_solar:this._t("charge_mode_min_plus_solar"),always_max:this._t("charge_mode_always_max"),off:this._t("charge_mode_off")},st=Math.round(this._entityVal("number.sem_battery_buffer_soc",70)),it=Math.round(this._entityVal("number.sem_battery_priority_soc",30)),rt=t=>(this._t(t)||"").replace(/\{buffer\}/g,st).replace(/\{priority\}/g,it),at=rt(`charge_mode_hint_${O}_surplus`),nt=rt(`charge_mode_hint_${O}_overnight`),ot=rt(`charge_mode_hint_${O}_battery`),lt=`select.sem_charger_${t}_ev_target_type`,ct=this._stateStr(lt)||"kwh",dt=this._stateAttrs(lt).options||["kwh"],pt="soc"===ct,_t=pt?`number.sem_charger_${t}_target_soc`:`number.sem_charger_${t}_daily_ev_target`,ht=pt?`number.sem_charger_${t}_target_soc_max`:`number.sem_charger_${t}_daily_ev_target_max`,gt=`time.sem_charger_${t}_target_time`,mt=this._stateStr(gt),ft=mt?mt.slice(0,5):"—",yt=this._stateAttrs(`${this._prefix}charging_state`),vt=!1===yt.ev_deadline_reachable,bt=this._departureFor(t,yt),xt=mt?mt.slice(0,5):bt.default||"07:00",$t=yt.ev_next_cheap_window;let wt="";if($t)try{const t=new Date($t);isNaN(t)||(wt=t.toLocaleTimeString([],{hour:"2-digit",minute:"2-digit",timeZone:this._hass?.config?.time_zone||void 0}))}catch(t){}const kt="solar_plus_cheap"===O&&wt,St=`select.sem_charger_${t}_phase_mode`,Ct=!!this._hass?.states?.[St],zt=(yt.per_charger_phases||{})[t]||{},Mt=this._stateStr(St)||"auto",Dt=this._stateAttrs(St).options||["auto","1","3"],Et={auto:this._t("phase_mode_auto"),1:this._t("phase_mode_1"),3:this._t("phase_mode_3")};let Nt="";Nt="stopping"===zt.switch_state?this._t("phase_status_stopping"):"settling"===zt.switch_state?this._t("phase_status_settling"):zt.active_phases?(this._t("phase_status_measured")||"{n}-phase measured").replace("{n}",zt.active_phases):zt.believed_phases?(this._t("phase_status_believed")||"{n}-phase").replace("{n}",zt.believed_phases):this._t("phase_status_unknown");const Ft=this._entityVal(_t,pt?80:10),At=null==(pt?c:o)?null:pt?Math.max(0,(Ft-c)/100*M):Math.max(0,Ft-o),Tt=null!=At&&D>0?Math.round(At/D*100):null,It=dt.length>1?H`<select class="ct-unit" .value=${ct}
                    @click=${t=>t.stopPropagation()}
                    @change=${t=>this._selectOption(lt,t.target.value)}>
                    ${dt.map(t=>H`<option value=${t} ?selected=${t===ct}>${"soc"===t?"%":"kWh"}</option>`)}
                </select>`:H`<span class="ct-unit-static">${pt?"%":"kWh"}</span>`,Rt=this._allSettings,Bt=this._nextDeparture(bt),[Ot,Lt=""]=(this._t("ev_dep_next")||"{when}").split("{when}"),Pt=Object.keys(bt.by_weekday||{}).length>0,Ut=t=>this.dispatchEvent(new CustomEvent("hass-more-info",{bubbles:!0,composed:!0,detail:{entityId:t}})),Wt=`number.sem_charger_${t}_minimum_current`,Ht=`number.sem_charger_${t}_ev_battery_capacity_kwh`,jt=`number.sem_charger_${t}_ev_kwh_per_100km`,Gt=t=>this._showHelp?H`<div class="setting-help">${this._t(t)}</div>`:K,Kt=H`
            <ha-icon
                class="ev-help-toggle ${this._showHelp?"on":""}"
                icon="${this._showHelp?"mdi:help-circle":"mdi:help-circle-outline"}"
                title="${this._t("zone_help_toggle")}"
                @click=${()=>this._toggleHelp()}
                style="--mdc-icon-size:16px"
            ></ha-icon>`,qt=H`
            ${I?H`
            <div class="ct-row">
                <span class="ct-label">${this._t("pause_charging_for")}</span>
                <span class="ct-ctl ct-pause">
                    <select class="ct-mode-select ct-pause-select"
                            .value=${F}
                            @click=${t=>t.stopPropagation()}
                            @change=${t=>this._selectOption(E,t.target.value)}>
                        ${A.map(t=>H`
                            <option value=${t} ?selected=${t===F}>
                                ${this._t(`pause_duration_${t}`)||t}
                            </option>`)}
                    </select>
                    <button class="ct-pause-btn"
                            @click=${t=>{t.stopPropagation(),this._pressButton(T)}}
                            title=${this._t("pause_charging_hint")}>
                        <ha-icon icon="mdi:pause-octagon-outline" style="--mdc-icon-size:15px"></ha-icon>
                        ${U?this._t("pause_charging_again"):this._t("pause_charging")}
                    </button>
                </span>
            </div>
            `:K}
            ${Ct?H`
            <div class="ct-row">
                <span class="ct-label">${this._t("phase_mode")}</span>
                <span class="ct-ctl">
                    <select class="ct-mode-select"
                            .value=${Mt}
                            @click=${t=>t.stopPropagation()}
                            @change=${t=>this._selectOption(St,t.target.value)}>
                        ${Dt.map(t=>H`
                            <option value=${t} ?selected=${t===Mt}>
                                ${Et[t]||t}
                            </option>`)}
                    </select>
                </span>
            </div>
            <div class="ct-subhint">
                <div class="ct-hint-row">
                    <span class="ct-hint-text">
                        <ha-icon icon="mdi:sine-wave" style="--mdc-icon-size:12px;color:#8DC892"></ha-icon>
                        ${Nt}
                    </span>
                </div>
            </div>
            `:K}
            ${this._renderDepartureRows(t,bt,xt)}
            ${this._renderBoostRow(t,bt,yt)}
        `,Vt=H`
            ${Rt?K:H`
            <div class="details-now">
                <span><span class="cm-label">${this._t("session")}</span>
                    <span class="cm-value">${this._fmt(n,1)} kWh</span></span>
                ${C>0?H`
                <span><span class="cm-label">${this._t("commanded_current")}</span>
                    <span class="cm-value">${Math.round(C)}&nbsp;A</span></span>`:K}
            </div>`}
            ${this._renderPlanStrip(t)}
            ${h?H`
            <div class="soc-info-708 soc-info-708-stop">
                <ha-icon icon="mdi:check-circle-outline" style="--mdc-icon-size:14px;color:#8DC892"></ha-icon>
                <span>${y("soc_target_reached_est")}<br>
                    <small>${y("soc_confirms_next_update")}</small></span>
            </div>`:v?H`
            <div class="soc-info-708">
                <ha-icon icon="mdi:information-outline" style="--mdc-icon-size:14px;color:#5BC8D8"></ha-icon>
                <span>${y("soc_info_line")}</span>
            </div>`:K}
            ${"solar_plus_battery"===O&&Q?H`
            <div class="ct-subhint">
                <div class="ct-hint-row">
                    <ha-icon icon="mdi:school-outline" style="--mdc-icon-size:13px;color:#5BC8D8"></ha-icon>
                    <span class="ct-hint-text">${tt}</span>
                </div>
            </div>
            `:K}
            ${this._renderSessions(t)}
        `;return H`
            <div class="charger-section">
                <div class="charger-header">
                    <div class="charger-dot" style="background:${s}"></div>
                    <span class="charger-name">${b}</span>
                    <span class="charger-status" style="color:${w?s:""}">${S}${Rt&&C>0?H` <span class="charger-set">(${Math.round(C)}&nbsp;A)</span>`:K}</span>
                </div>

                <div class="charger-body">
                    <div class="charger-soc" title="${d?this._t("soc_estimated_hint"):""}">
                        ${this._renderSocGauge(c,d)}
                        <span class="soc-label">${d?this._t("soc_estimated_label"):"SOC"}</span>
                    </div>

                    <div class="charger-metrics">
                        <div class="cm-row">
                            <span class="cm-label">${this._t("power")}</span>
                            <span class="cm-value" style="color:${w?s:""}">${ut(i)}</span>
                        </div>
                        <div class="cm-row">
                            <span class="cm-label">${this._t("today")}</span>
                            <span class="cm-value">${this._fmt(o,1)} kWh</span>
                        </div>
                        ${Rt?H`
                        <div class="cm-row">
                            <span class="cm-label">${this._t("session")}</span>
                            <span class="cm-value">${this._fmt(n,1)} kWh</span>
                        </div>`:K}
                        <div class="cm-row">
                            <span class="cm-label">${this._t("solar_share")}</span>
                            <span class="cm-value" style="color:#ff9800">${this._fmt(l,0)}%</span>
                        </div>
                        <!-- (#440) "Charge Tonight" and "Nights Until Charge"
                             rows removed. The underlying skip-decision wiring
                             was removed alongside; charge mode is the sole
                             authority on whether to charge at night. -->
                    </div>
                </div>

                <div class="charge-target-group">
                    <div class="ct-title">
                        <ha-icon icon="mdi:target" style="--mdc-icon-size:14px;color:#8DC892"></ha-icon>
                        ${this._t("charge_target")}
                        ${null!=Tt&&Tt>0?H`<span class="ct-range">· +${Tt} km</span>`:K}
                        <span class="ct-spacer"></span>
                        ${It}
                    </div>
                    ${this._renderRangeSlider(_t,ht,pt)}
                    <!-- #277 Phase B.2: one named Charge mode selector
                         replaces the legacy ev_grid_charging + nested
                         ev_tariff_mode toggles. Options come from the HA
                         entity itself (solar_plus_cheap is hidden when no
                         dynamic tariff is configured, per Q1). The hint
                         line under it explains what the selected mode
                         actually does — cuts the toggle-soup mystery the
                         #247 review flagged. -->
                    <div class="ct-row">
                        <span class="ct-label">${this._t("charge_mode")}</span>
                        <span class="ct-ctl">
                            <select class="ct-mode-select"
                                    .value=${O}
                                    @click=${t=>t.stopPropagation()}
                                    @change=${t=>this._selectOption(R,t.target.value)}>
                                ${V.map(t=>H`
                                    <option value=${t} ?selected=${t===O}
                                            ?disabled=${X(t)}>
                                        ${et[t]||t}${X(t)?` — ${this._t("charge_mode_needs_tariff")}`:""}
                                    </option>`)}
                            </select>
                        </span>
                    </div>
                    ${U?H`
                    <!-- A running pause is what the mode reads Off for: it
                         stays beside the mode in both views; the button that
                         starts one is under More. -->
                    <div class="ct-subhint">
                        <div class="ct-hint-row">
                            <ha-icon icon="mdi:pause-circle-outline" style="--mdc-icon-size:13px;color:#8DC892"></ha-icon>
                            <span class="ct-hint-text">${W>0?H`${(this._t("pause_status_line")||"").replace("{left}",q).replace("{mode}",et[j]||j).replace("{time}",G)}
                                    <span style="opacity:.75"> ${this._t("pause_resume_hint")}</span>`:this._t("pause_resuming")}</span>
                        </div>
                    </div>
                    `:K}
                    ${this._showHelp?H`
                    <div class="ct-subhint">
                        <div class="ct-hint-row">
                            <span class="ct-hint-label">${this._t("hint_label_surplus")}:</span>
                            <span class="ct-hint-text">${at}</span>
                        </div>
                        <div class="ct-hint-row">
                            <span class="ct-hint-label">${this._t("hint_label_overnight")}:</span>
                            <span class="ct-hint-text">${nt}</span>
                        </div>
                        <div class="ct-hint-row">
                            <span class="ct-hint-label">${this._t("hint_label_battery")}:</span>
                            <span class="ct-hint-text">${ot}</span>
                        </div>
                        ${kt?H`
                            <div class="ct-hint-row ct-hint-extra">
                                <span class="ct-hint-label">${this._t("ev_next_cheap")}:</span>
                                <span class="ct-hint-text"><b style="color:#8DC892">${wt}</b></span>
                            </div>
                        `:K}
                    </div>
                    `:kt?H`
                        <div class="ct-cheap-hint">
                            <span class="ct-hint-label">${this._t("ev_next_cheap")}:</span>
                            <b style="color:#8DC892">${wt}</b>
                        </div>
                    `:K}
                    <div class="ct-row clickable charge-by-row"
                        @click=${()=>Ut(gt)}>
                        <span class="ct-label">${this._t("ev_charge_by")}</span>
                        <span class="ct-ctl ct-time">
                            <ha-icon icon="mdi:clock-end" style="--mdc-icon-size:13px;color:#5BC8D8"></ha-icon>
                            ${ft}
                            ${Pt?H`<span class="dep-most">· ${this._t("ev_dep_most_days")}</span>`:K}
                        </span>
                    </div>
                    ${(Pt||bt.from_calendar)&&Bt.label?H`
                    <!-- (#1023) A weekday with its own time makes the next
                         departure worth saying; otherwise it is Charge by.
                         (#1087) A calendar event names itself too. -->
                    <div class="ct-subhint dep-hint">
                        <div class="ct-hint-row">
                            <span class="ct-hint-text">${bt.from_calendar?this._fmtT("ev_dep_next_calendar",{when:Bt.label,event:bt.calendar_summary||""}):H`${Ot}<b class="dep-next">${Bt.label}</b>${Lt}`}</span>
                        </div>
                    </div>`:K}
                    ${vt?H`
                        <div class="ct-warn">
                            <ha-icon icon="mdi:clock-alert" style="--mdc-icon-size:14px;color:#f06292"></ha-icon>
                            <span>${this._t("ev_deadline_unreachable_short")}</span>
                        </div>
                    `:K}
                    ${this._renderFold(t,"more","ev_fold_more",qt)}
                </div>

                ${this._renderFold(t,"details","ev_fold_details",Vt)}

                ${Rt?H`
                <div class="charger-settings ${this._showHelp?"help-mode":""}">
                    ${""}
                    <div class="setting-cell">
                        <div class="setting-item clickable" @click=${()=>Ut(Wt)}>
                            <ha-icon icon="mdi:speedometer-slow" style="--mdc-icon-size:16px;color:#ff9800"></ha-icon>
                            <span class="setting-value">${this._fmt(z,0)}A</span>
                        </div>
                        ${Gt("tile_help_min_amps")}
                    </div>
                    <div class="setting-cell">
                        <div class="setting-item clickable" @click=${()=>Ut(Ht)}>
                            <ha-icon icon="mdi:car-battery" style="--mdc-icon-size:16px;color:#8DC892"></ha-icon>
                            <span class="setting-value">${this._fmt(M,0)} kWh</span>
                        </div>
                        ${Gt("tile_help_capacity")}
                    </div>
                    <div class="setting-cell">
                        <div class="setting-item clickable" @click=${()=>Ut(jt)}>
                            <ha-icon icon="mdi:map-marker-distance" style="--mdc-icon-size:16px;color:#5BC8D8"></ha-icon>
                            <span class="setting-value">${this._fmt(D,0)} kWh/100km</span>
                        </div>
                        ${Gt("tile_help_consumption")}
                    </div>
                    ${Kt}
                </div>`:H`
                <!-- Everyday: the three set-once values on one line; each
                     opens the same more-info its tile does. -->
                <div class="set-once">
                    <span class="set-once-label">${this._t("ev_set_once")}:</span>
                    <button class="set-once-val" type="button" @click=${()=>Ut(Ht)}>${this._fmt(M,0)} kWh</button>
                    <span class="set-once-sep">·</span>
                    <button class="set-once-val" type="button" @click=${()=>Ut(Wt)}>${this._fmt(z,0)} A</button>
                    <span class="set-once-sep">·</span>
                    <button class="set-once-val" type="button" @click=${()=>Ut(jt)}>${this._fmt(D,0)} kWh/100 km</button>
                    ${Kt}
                </div>
                ${this._showHelp?H`
                <div class="set-once-help">
                    ${Gt("tile_help_capacity")}
                    ${Gt("tile_help_min_amps")}
                    ${Gt("tile_help_consumption")}
                </div>`:K}`}
            </div>
        `}render(){if(!this._config||!this._hass)return K;const t=this._binaryState("ev_connected"),e=(this._chargers||[]).map(t=>this._val(`charger_${t}_power`)),s=e.length?e.every(t=>null==t)?null:e.reduce((t,e)=>t+(e??0),0):this._val("ev_power"),i=s>50;this._val("calculated_current",0),this._val("session_energy",0);const r=this._val("energy_ev_solar_percentage"),a=this._val("session_cost"),n=this._val("daily_ev_energy");this._valStr("charging_state");const o=ft(this._hass),l=i?"wrap state-charging":t?"wrap state-connected":"wrap state-disconnected",c=i?this._t("charging"):t?this._t("connected"):this._t("disconnected"),d=i?"status-value charging":t?"status-value connected":"status-value disconnected",p=i?"0.6":t?"0.25":"0.08",_=i?"1":"0";return H`
            <svg class="glow-svg">
                <defs>
                    <filter id="ev-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="3" result="blur"/>
                        <feFlood flood-color="#8DC892" flood-opacity="0.3" result="color"/>
                        <feComposite in="color" in2="blur" operator="in" result="glow"/>
                        <feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                    <filter id="ev-glow-soft" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="6" result="blur"/>
                        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                </defs>
            </svg>

            <ha-card>
                <div class="${l}">
                    ${this._chargers.length>=1?H`
                    <!-- The same switch as on the Configuration tab: one
                         setting for every SEM card, kept per browser. -->
                    <div class="view-switch" role="group" aria-label=${this._t("ev_view_label")}>
                        <button class="view-seg ${this._allSettings?"":"on"}" type="button"
                                aria-pressed=${this._allSettings?"false":"true"}
                                @click=${()=>this._setView(!1)}>${this._t("ev_view_everyday")}</button>
                        <button class="view-seg ${this._allSettings?"on":""}" type="button"
                                aria-pressed=${this._allSettings?"true":"false"}
                                @click=${()=>this._setView(!0)}>${this._t("ev_view_all")}</button>
                    </div>`:K}
                    <div class="hero">
                        <div class="ev-icon-area">
                            <svg viewBox="0 0 100 100">
                                <circle class="glow-ring" cx="50" cy="50" r="42" style="opacity:${p}"/>
                                <circle class="ring-bg" cx="50" cy="50" r="42"/>
                                <circle class="ring-fill" cx="50" cy="50" r="39"/>
                                <g class="charger-icon" transform="translate(50,46)">
                                    <rect x="-10" y="-16" width="20" height="26" rx="3"/>
                                    <rect x="-6.5" y="-11" width="13" height="10" rx="2"/>
                                    <path d="M-1.5,-1 L0,4 L1.5,-1"/>
                                    <line x1="0" y1="10" x2="0" y2="15"/>
                                    <circle class="indicator-dot" cx="0" cy="18" r="2" stroke="none"/>
                                </g>
                                <g class="lightning-bolt" transform="translate(50,42)" style="opacity:${_}">
                                    <path d="M-2,-8 L-4,1 L-0.5,0 L-1,8 L4,-1 L0.5,0 L2,-8Z" stroke="none"/>
                                </g>
                            </svg>
                        </div>

                        ${this._chargers.length>=1?H`
                            <!-- #356: when at least one per-charger section
                                 will render below, the hero only shows a
                                 single status/power line. The per-charger
                                 section repeats today/session/solar-share/
                                 power for each charger, so duplicating them
                                 here as well produced the "4 tiles per
                                 charger" appearance the user reported. -->
                            <div class="metrics-col compact">
                                <div class="metric-row">
                                    <span class="metric-label">${this._t("status")}</span>
                                    <span class="${d}">${c}</span>
                                </div>
                                ${i?H`
                                    <div class="metric-row power-row">
                                        <span class="metric-label">${this._t("power")}</span>
                                        <span class="metric-value power-value">${ut(s)}</span>
                                    </div>
                                `:K}
                            </div>
                        `:H`
                            <div class="metrics-col">
                                <div class="metric-row">
                                    <span class="metric-label">${this._t("status")}</span>
                                    <span class="${d}">${c}</span>
                                </div>
                                ${i?H`
                                    <div class="metric-row power-row">
                                        <span class="metric-label">${this._t("power")}</span>
                                        <span class="metric-value power-value">${ut(s)}</span>
                                    </div>
                                `:K}
                                <div class="metric-row">
                                    <span class="metric-label">${this._t("today")}</span>
                                    <span class="metric-value">${this._fmt(n,1)} kWh</span>
                                </div>
                                <div class="metric-row">
                                    <span class="metric-label">${this._t("solar_share")}</span>
                                    <span class="metric-value solar-share-value">${this._fmt(r,0)}%</span>
                                </div>
                            </div>
                        `}
                    </div>

                    <!-- Session cost chip stays on for 0- and 1-charger
                         installs (M3 reviewer note): the global
                         sem_session_cost sensor IS the single charger's
                         cost. Only hide for multi-charger setups where
                         the global is a fleet aggregate and per-charger
                         attribution lives in each section's metrics. -->
                    ${this._chargers.length>1?K:H`
                        <div class="bottom-bar">
                            <div class="chip">
                                <span class="chip-label">${this._t("session_cost")}</span>
                                <span class="cost-chip-value">${this._fmt(a,2)} ${o}</span>
                            </div>
                        </div>
                    `}

                    ${this._chargers.length>=1?H`
                        <div class="charger-sections">
                            ${this._chargers.map((t,e)=>this._renderChargerSection(t,e))}
                        </div>
                    `:K}
                </div>
            </ha-card>
        `}static get styles(){return a`
            :host { display: block; }
            .glow-svg { position: absolute; width: 0; height: 0; }

            .wrap {
                padding: 16px 20px;
                position: relative;
                background:
                    radial-gradient(ellipse 70% 60% at 50% 25%, rgba(141,200,146,0.06) 0%, transparent 100%),
                    radial-gradient(circle at 2px 2px, rgba(128,128,128,0.05) 0.7px, transparent 0.7px);
                background-size: 100% 100%, 50px 50px;
                font-family: 'Segoe UI','Roboto',sans-serif;
                color: var(--primary-text-color, #e0e0e0);
                min-height: 108px;
                overflow: hidden;
            }

            /* Hero layout */
            .hero {
                display: flex;
                align-items: center;
                gap: 20px;
            }

            /* Icon area */
            .ev-icon-area {
                position: relative;
                width: 90px; height: 90px;
                flex-shrink: 0;
            }
            .ev-icon-area svg { width: 100%; height: 100%; }

            /* Glow ring */
            .glow-ring {
                fill: none;
                stroke: #8DC892;
                stroke-width: 6;
                filter: url(#ev-glow-soft);
                transition: opacity 0.6s ease;
            }
            .state-charging .glow-ring {
                animation: pulse-ring 2s ease-in-out infinite;
            }
            @keyframes pulse-ring {
                0%, 100% { stroke-width: 6; opacity: 0.5; }
                50% { stroke-width: 10; opacity: 0.7; }
            }

            .ring-bg {
                fill: none;
                stroke: rgba(141,200,146,0.12);
                stroke-width: 3;
            }
            .ring-fill {
                fill: rgba(141,200,146,0.07);
            }

            .charger-icon {
                stroke: #8DC892;
                fill: none;
                stroke-width: 1.8;
                stroke-linecap: round;
                stroke-linejoin: round;
                opacity: 0.7;
                transition: opacity 0.4s ease;
            }
            .state-disconnected .charger-icon { stroke: #666; opacity: 0.35; }
            .state-disconnected .ring-bg { stroke: rgba(100,100,100,0.12); }
            .state-disconnected .ring-fill { fill: rgba(100,100,100,0.05); }
            .state-disconnected .glow-ring { stroke: #666; }

            .lightning-bolt {
                fill: #8DC892;
                transition: opacity 0.4s ease;
                filter: url(#ev-glow);
            }
            .state-charging .lightning-bolt {
                animation: bolt-pulse 1.5s ease-in-out infinite;
            }
            @keyframes bolt-pulse {
                0%, 100% { opacity: 0.9; }
                50% { opacity: 0.5; }
            }

            .indicator-dot {
                fill: #666;
                opacity: 0.3;
                transition: fill 0.4s ease, opacity 0.4s ease;
            }
            .state-connected .indicator-dot { fill: #8DC892; opacity: 0.5; }
            .state-charging .indicator-dot {
                fill: #8DC892; opacity: 1;
                animation: dot-blink 1s ease-in-out infinite;
            }
            @keyframes dot-blink {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.3; }
            }

            /* Metrics column */
            .metrics-col {
                flex: 1; min-width: 0;
                display: flex;
                flex-direction: column;
                gap: 2px;
            }
            .metric-row {
                display: flex;
                justify-content: space-between;
                align-items: baseline;
                gap: 8px;            /* #523/#524 follow-up: keep label + value
                                        apart when the column shrink-wraps in
                                        the centered hero ("StatusDisconnected") */
                padding: 2px 0;
            }
            .metric-label {
                font-size: 11px;
                color: var(--secondary-text-color, #999);
                font-weight: 500;
            }
            .metric-value {
                font-size: 12px;
                font-weight: 600;
                font-variant-numeric: tabular-nums;
                color: var(--primary-text-color, #e0e0e0);
            }

            .status-value { font-size: 13px; font-weight: 700; font-variant-numeric: tabular-nums; }
            .status-value.charging { color: #8DC892; text-shadow: 0 0 8px rgba(141,200,146,0.4); }
            .status-value.connected { color: #8DC892; }
            .status-value.disconnected { color: var(--secondary-text-color, #999); }

            .power-row .metric-value {
                font-size: 16px;
                font-weight: 700;
                color: #8DC892;
                text-shadow: 0 0 6px rgba(141,200,146,0.3);
            }

            .solar-share-value { color: #ff9800 !important; }

            .strategy-value {
                font-size: 11px;
                color: #8DC892; opacity: 0.7;
                font-weight: 500;
                white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
            }

            /* Bottom bar */
            .bottom-bar {
                display: flex;
                align-items: center;
                gap: 8px;
                margin-top: 10px;
                flex-wrap: wrap;
            }
            .chip {
                display: inline-flex; align-items: center; gap: 4px;
                background: var(--secondary-background-color, rgba(255,255,255,0.06));
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius: 12px;
                padding: 3px 10px;
                font-size: 11px; font-weight: 500;
                color: var(--primary-text-color, #e0e0e0);
                font-variant-numeric: tabular-nums;
            }
            .chip-label { color: var(--secondary-text-color, #888); }
            .cost-chip-value { color: #f06292; }

            /* Per-charger sections */
            .charger-sections {
                margin-top: 16px;
                display: flex;
                flex-direction: column;
                gap: 12px;
            }
            .charger-section {
                background: var(--secondary-background-color, rgba(255,255,255,0.06));
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius: 12px;
                padding: 12px 14px;
            }
            .charger-header {
                display: flex; align-items: center; gap: 8px;
                margin-bottom: 10px;
            }
            .charger-dot {
                width: 8px; height: 8px;
                border-radius: 50%;
                flex-shrink: 0;
            }
            .charger-name {
                flex: 1; font-weight: 600; font-size: 0.95em;
                color: var(--primary-text-color, #e0e0e0);
            }
            .charger-status {
                font-size: 0.8em; font-weight: 500;
                text-transform: uppercase; letter-spacing: 0.05em;
                color: var(--secondary-text-color, #999);
            }
            .charger-set {
                font-weight: 400; opacity: 0.85;
                font-variant-numeric: tabular-nums;
            }
            .charger-body {
                display: flex; align-items: center; gap: 12px;
            }
            .charger-soc {
                flex-shrink: 0; width: 44px; text-align: center;
            }
            .soc-label {
                display: block;
                font-size: 10px; color: var(--secondary-text-color, #999);
                margin-top: 2px;
                text-transform: uppercase; letter-spacing: 0.05em;
            }
            .charger-metrics {
                flex: 1;
                display: flex; flex-direction: column; gap: 2px;
            }
            /* #708 — stale-sensor estimate info line */
            .soc-info-708 {
                display: flex; align-items: flex-start; gap: 6px;
                margin: 4px 0 2px; padding: 4px 8px;
                font-size: 11px; line-height: 1.35;
                color: var(--secondary-text-color, #999);
                background: rgba(91, 200, 216, 0.08);
                border-radius: 6px;
            }
            .soc-info-708-stop {
                background: rgba(141, 200, 146, 0.10);
                color: var(--primary-text-color, #c9d4c9);
            }
            .soc-info-708 small {
                font-size: 10px; opacity: 0.75;
            }
            .cm-row {
                display: flex; justify-content: space-between; align-items: baseline;
                padding: 2px 0;
            }
            .cm-label { font-size: 11px; color: var(--secondary-text-color, #999); font-weight: 500; }
            .cm-value {
                font-size: 12px; font-weight: 600;
                color: var(--primary-text-color, #e0e0e0);
                font-variant-numeric: tabular-nums;
            }
            .charger-settings {
                display: flex; align-items: center; gap: 6px;
                margin-top: 8px; padding-top: 8px;
                border-top: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                flex-wrap: wrap;
            }
            /* Help mode: switch to a vertical list so each tile gets a
               one-line description below it. Compact when off. */
            .charger-settings.help-mode {
                flex-direction: column; align-items: stretch; gap: 4px;
            }
            .setting-cell { display: flex; align-items: center; gap: 6px; }
            .charger-settings.help-mode .setting-cell {
                flex-direction: column; align-items: flex-start; gap: 2px;
            }
            .setting-help {
                font-size: 11px;
                line-height: 1.3;
                color: var(--secondary-text-color, #888);
                opacity: 0.85;
                font-style: italic;
                padding-left: 22px;
            }
            .ev-help-toggle {
                cursor: pointer;
                color: var(--secondary-text-color, #999);
                opacity: 0.6;
                margin-left: auto;
                flex-shrink: 0;
                transition: opacity 0.15s, color 0.15s;
            }
            .ev-help-toggle:hover { opacity: 1; }
            .ev-help-toggle.on { color: #8DC892; opacity: 1; }
            .charger-settings.help-mode .ev-help-toggle { align-self: flex-end; }
            .setting-item {
                display: flex; align-items: center; gap: 3px;
                font-size: 11px; color: var(--secondary-text-color, #999);
            }
            .setting-item.clickable { cursor: pointer; }
            .setting-label { font-size: 11px; color: var(--secondary-text-color, #999); }
            .setting-value { font-size: 12px; font-weight: 600; color: var(--primary-text-color, #e0e0e0); }
            .setting-toggle {
                font-size: 11px; font-weight: 700;
                padding: 1px 6px;
                border-radius: 6px;
                cursor: pointer;
                user-select: none;
                transition: background 0.2s, color 0.2s;
            }
            .setting-toggle.on  { background: rgba(121,134,203,0.25); color: #7986CB; }
            .setting-toggle.off { background: rgba(100,100,100,0.15); color: #666; }
            .setting-toggle:hover { opacity: 0.8; }

            /* The view switch: Everyday | All settings */
            .view-switch {
                display: flex; justify-content: flex-end;
                margin: -6px -8px 6px 0;
            }
            .view-seg {
                font: inherit; font-size: 11px; font-weight: 600;
                padding: 3px 10px; min-height: 24px;
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                background: transparent; cursor: pointer;
                color: var(--secondary-text-color, #999);
            }
            .view-seg:first-child { border-radius: 8px 0 0 8px; }
            .view-seg:last-child { border-radius: 0 8px 8px 0; border-left: none; }
            .view-seg.on { background: rgba(141,200,146,0.18); color: #8DC892; }
            .view-seg:focus-visible, .fold-btn:focus-visible, .set-once-val:focus-visible {
                outline: 2px solid #8DC892; outline-offset: 1px;
            }
            /* Folds: More (inside Charge Target) and Details (below it) */
            .fold-btn {
                display: flex; align-items: center; justify-content: space-between;
                width: 100%; min-height: 32px; padding: 4px 0;
                font: inherit; font-size: 11px; font-weight: 600;
                text-transform: uppercase; letter-spacing: 0.05em;
                color: var(--secondary-text-color, #999);
                background: none; border: none; cursor: pointer;
                border-top: 1px solid rgba(255,255,255,0.06);
            }
            .fold-btn:hover { color: var(--primary-text-color, #e0e0e0); }
            .fold-details { margin-top: 8px; padding: 0 2px; }
            .fold-details > .fold-btn { border-top: none; }
            .details-now {
                display: flex; flex-wrap: wrap; gap: 4px 14px;
                padding: 2px 0 4px;
            }
            .details-now > span { display: inline-flex; gap: 6px; align-items: baseline; }
            /* Everyday: the three set-once values on one line */
            .set-once {
                display: flex; align-items: center; flex-wrap: wrap; gap: 4px;
                margin-top: 8px; padding-top: 8px;
                border-top: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                font-size: 11px; color: var(--secondary-text-color, #999);
            }
            .set-once-val {
                font: inherit; font-size: 12px; font-weight: 600;
                color: var(--primary-text-color, #e0e0e0);
                background: none; border: none; padding: 2px; cursor: pointer;
                font-variant-numeric: tabular-nums;
            }
            .set-once-val:hover { text-decoration: underline; }
            .set-once-help { display: flex; flex-direction: column; gap: 2px; margin-top: 4px; }
            .set-once-help .setting-help { padding-left: 0; }

            /* Charge Target group (#235) */
            .charge-target-group {
                margin-top: 8px;
                padding: 10px 12px;
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius: 10px;
                background: rgba(255,255,255,0.025);
            }
            .ct-title {
                font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
                color: var(--secondary-text-color, #999);
                display: flex; align-items: center; gap: 5px;
                margin-bottom: 4px;
            }
            .ct-range { color: #5BC8D8; font-weight: 600; text-transform: none; letter-spacing: 0; }
            .ct-spacer { margin-left: auto; }
            /* Dual-handle charge-target range slider (#245) */
            .range-wrap { padding: 6px 8px 10px; }
            .range-labels {
                display: flex; justify-content: space-between;
                font-size: 12px; color: var(--primary-text-color, #e0e0e0);
                margin-bottom: 10px;
            }
            .range-labels b { font-variant-numeric: tabular-nums; }
            .range-track {
                position: relative; height: 6px; border-radius: 3px;
                background: rgba(255,255,255,0.14); margin: 6px 9px;
                touch-action: none;
            }
            .range-fill {
                position: absolute; top: 0; height: 100%; border-radius: 3px;
                background: linear-gradient(90deg, #8DC892, #ff9800);
            }
            .range-handle {
                position: absolute; top: 50%; width: 18px; height: 18px;
                border-radius: 50%; transform: translate(-50%, -50%);
                background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.5);
                cursor: grab; touch-action: none;
            }
            .range-handle:active { cursor: grabbing; }
            .range-handle-min { border: 3px solid #8DC892; }
            .range-handle-max { border: 3px solid #ff9800; }
            .ct-row {
                display: flex; align-items: center; min-height: 32px;
            }
            .ct-row + .ct-row { border-top: 1px solid rgba(255,255,255,0.06); }
            .ct-row.clickable { cursor: pointer; }
            /* Tariff is nested under "Overnight grid charging" — it refines WHEN
               grid charging happens, not WHETHER (#247 UX). */
            .ct-subrow { padding-left: 14px; border-left: 2px solid rgba(141,200,146,0.35); margin-left: 2px; }
            .ct-subrow .ct-label { color: var(--secondary-text-color, #b5b5b5); }
            .ct-subhint {
                padding: 4px 0 4px 16px; margin-left: 2px;
                border-left: 2px solid rgba(141,200,146,0.18);
                font-size: 11px; line-height: 1.35; color: var(--secondary-text-color, #999);
                display: flex; flex-direction: column; gap: 2px;
            }
            .ct-hint-row { display: flex; gap: 6px; align-items: baseline; }
            .ct-hint-label {
                color: var(--secondary-text-color, #b5b5b5);
                font-weight: 600; flex-shrink: 0;
                min-width: 64px; text-align: right;
            }
            .ct-hint-text { color: var(--secondary-text-color, #999); }
            .ct-hint-extra { padding-top: 2px; border-top: 1px dashed rgba(255,255,255,0.05); }
            /* Cheap-window timing kept visible when help is off — too
               useful to hide behind the (?). One small line. */
            .ct-cheap-hint {
                padding: 3px 0 0 16px; margin-left: 2px;
                border-left: 2px solid rgba(141,200,146,0.18);
                font-size: 11px; color: var(--secondary-text-color, #999);
                display: flex; gap: 6px; align-items: baseline;
            }
            .ct-cheap-hint .ct-hint-label {
                min-width: auto; text-align: left;
            }
            .ct-label { font-size: 12px; color: var(--primary-text-color, #e0e0e0); }
            .ct-ctl { margin-left: auto; display: flex; align-items: center; gap: 7px; }
            .ct-time {
                font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums;
                color: var(--primary-text-color, #e0e0e0);
            }
            .ct-warn {
                display: flex; align-items: center; gap: 6px;
                font-size: 12px; color: #f06292; padding: 5px 0 2px;
            }
            /* (#1023/#1025) Departure + boost rows — approved mockup 06.10 */
            .dep-most { font-weight: 400; color: var(--secondary-text-color, #9b9b9b); }
            .dep-days {
                display: flex; gap: 4px; padding: 2px 0 6px 16px; margin-left: 2px;
                border-left: 2px solid rgba(91,200,216,0.25);
            }
            .dep-day {
                flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: center;
                gap: 1px; padding: 3px 0 4px; border-radius: 7px; cursor: pointer;
                font: inherit; color: inherit;
                border: 1px solid rgba(255,255,255,0.10); background: rgba(255,255,255,0.03);
            }
            .dep-day .d {
                font-size: 10px; letter-spacing: .03em; text-transform: uppercase;
                color: var(--secondary-text-color, #9b9b9b);
                max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
            }
            .dep-day .t { font-size: 11px; font-weight: 600; font-variant-numeric: tabular-nums; color: #8a8a8a; }
            .dep-day.own { border-color: rgba(91,200,216,0.55); background: rgba(91,200,216,0.10); }
            .dep-day.own .t { color: #5BC8D8; }
            .dep-day.next { box-shadow: 0 0 0 1px #5BC8D8 inset; }
            .dep-day.open { background: rgba(91,200,216,0.22); }
            .dep-hint { border-left-color: rgba(91,200,216,0.25); }
            .dep-next { color: #5BC8D8; }
            .dep-time-input {
                background: var(--secondary-background-color, rgba(255,255,255,0.07));
                color: var(--primary-text-color, #e0e0e0);
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius: 8px; padding: 3px 8px; font: inherit; font-size: 12px;
                font-weight: 600; color-scheme: dark light;
            }
            .dep-clear, .ct-boost-btn {
                display: inline-flex; align-items: center; gap: 5px; cursor: pointer;
                border-radius: 8px; padding: 4px 10px; font: inherit; font-size: 12px; font-weight: 600;
            }
            .dep-clear {
                border: 1px solid rgba(91,200,216,0.45); color: #5BC8D8; background: rgba(91,200,216,0.10);
            }
            .ct-boost-btn {
                border: 1px solid rgba(77,182,172,.55); color: #4db6ac; background: rgba(77,182,172,.12);
            }
            .ct-boost-btn.stop {
                border-color: rgba(240,98,146,.5); color: #f06292; background: rgba(240,98,146,.10);
            }
            .ct-boost-btn[disabled] { opacity: .45; cursor: default; }
            .boost-row { margin-top: 6px; border-top: 1px solid rgba(255,255,255,0.06); }
            .boost-floor { color: #4db6ac; }
            .boost-hint { border-left-color: rgba(77,182,172,0.3); }
            .boost-bar {
                height: 6px; border-radius: 3px; background: rgba(255,255,255,.10);
                position: relative; margin: 5px 0 3px;
            }
            .boost-bar i {
                position: absolute; left: 0; top: 0; bottom: 0; border-radius: 3px; background: #4db6ac;
            }
            /* (#1024) Sessions list — approved mockup 01.10 */
            .sessions-block {
                margin: 10px 0 12px; padding: 8px 10px; border-radius: 12px;
                background: rgba(255,255,255,0.03);
            }
            .sessions-head { justify-content: space-between; cursor: pointer; margin-bottom: 0; }
            .sessions-name { display: flex; gap: 6px; align-items: center; }
            .sessions-month { padding: 8px 0 4px; }
            .sessions-nav { display: flex; gap: 10px; align-items: center; }
            .sessions-nav .nav { color: #5BC8D8; cursor: pointer; padding: 0 2px; }
            .sessions-nav .nav.off { opacity: 0.25; cursor: default; }
            .sessions-block .num { text-align: right; }
            .sessions-day { font-weight: 500; white-space: nowrap; }
            .sessions-span { color: #b5b5b5; font-weight: 400; }
            .sessions-foot { justify-content: space-between; min-height: 28px; }
            .sessions-foot .clickable { cursor: pointer; }
            .sessions-dl { color: #5BC8D8; display: flex; gap: 4px; align-items: center; cursor: pointer; }
            .sessions-note { padding: 8px 0 4px; }
            /* 12h EV plan strip (#282, readability pass #464) */
            .plan-strip {
                margin: 8px 0 2px; padding: 4px 0 2px;
                border-top: 1px dashed rgba(255,255,255,0.06);
            }
            .strip-title {
                display: flex; align-items: center; gap: 5px;
                font-size: 11px; font-weight: 600;
                color: var(--secondary-text-color, #aaa);
                letter-spacing: 0.3px; margin-bottom: 4px;
            }
            .strip-svg {
                width: 100%; height: 16px; display: block;
                border-radius: 3px; overflow: hidden;
            }
            .strip-axis {
                position: relative; height: 12px; margin-top: 2px;
                font-size: 10px; color: var(--secondary-text-color, #888);
            }
            .strip-axis .tick {
                position: absolute; transform: translateX(-50%);
                font-variant-numeric: tabular-nums; white-space: nowrap;
            }
            .strip-legend {
                display: flex; gap: 6px 11px; flex-wrap: wrap;
                font-size: 10.5px; color: var(--primary-text-color, #ddd);
                margin-top: 5px;
            }
            .strip-legend span {
                display: inline-flex; align-items: center; gap: 5px;
            }
            .strip-legend i {
                width: 11px; height: 11px; border-radius: 2px;
                display: inline-block; flex: none;
            }
            /* Tariff overlays render as a thin top line on the strip — mirror
               that shape in the legend so they read as the top line, not a
               full segment (#464). */
            .strip-legend i.line {
                height: 4px; border-radius: 1px;
            }
            /* (#1023) the top-up before departure, hatched like the strip */
            .strip-legend i.hatch {
                background: repeating-linear-gradient(135deg, #5BC8D8 0 3px, #3d97a3 3px 6px);
            }
            .strip-help { margin-top: 6px; }
            /* #355 — split affordance shown only when the two range
               handles share a value. Sits on top of the stacked
               handles; tapping it drops Min by one step so the
               handles become individually grabbable again. */
            .range-split {
                position: absolute; top: 50%;
                transform: translate(-50%, -50%);
                width: 22px; height: 22px; border-radius: 50%;
                display: flex; align-items: center; justify-content: center;
                background: rgba(0,0,0,0.55);
                color: #fff;
                cursor: pointer;
                box-shadow: 0 1px 3px rgba(0,0,0,0.5);
                pointer-events: auto;
                z-index: 2;
            }
            .range-split:hover { background: rgba(0,0,0,0.75); }
            .ct-val {
                background: rgba(141,200,146,0.14); color: #8DC892;
                border: 1px solid rgba(141,200,146,0.35);
                border-radius: 8px; padding: 3px 11px; font-weight: 600;
                font-variant-numeric: tabular-nums; min-width: 42px; text-align: center;
            }
            .ct-val.clickable { cursor: pointer; }
            .ct-unit {
                appearance: none; -webkit-appearance: none;
                background-color: var(--secondary-background-color, rgba(255,255,255,0.07));
                /* explicit caret — appearance:none drops the native arrow, which made
                   this look like a static label rather than a kWh/% toggle (#245) */
                background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23bbbbbb' d='M7 10l5 5 5-5z'/%3E%3C/svg%3E");
                background-repeat: no-repeat;
                background-position: right 3px center;
                background-size: 14px;
                color: var(--primary-text-color, #e0e0e0);
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius: 8px; padding: 4px 20px 4px 8px;
                font-size: 12px; font-weight: 600; cursor: pointer;
            }
            .ct-unit-static {
                font-size: 12px; font-weight: 600;
                color: var(--secondary-text-color, #999); padding: 4px 2px;
            }
            /* #277 Phase B.2 — Charge mode selector. Wider than ct-unit
               (multi-word labels) and aligned right inside the row's
               .ct-ctl cell. Same caret + chrome as ct-unit so the two
               selectors visually rhyme. */
            .ct-mode-select {
                appearance: none; -webkit-appearance: none;
                background-color: var(--secondary-background-color, rgba(255,255,255,0.07));
                background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23bbbbbb' d='M7 10l5 5 5-5z'/%3E%3C/svg%3E");
                background-repeat: no-repeat;
                background-position: right 6px center;
                background-size: 14px;
                color: var(--primary-text-color, #e0e0e0);
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius: 8px;
                padding: 4px 24px 4px 10px;
                font-size: 12px; font-weight: 600;
                cursor: pointer;
                max-width: 200px;
            }
            .ct-sw {
                width: 38px; height: 22px; border-radius: 12px;
                position: relative; cursor: pointer; flex-shrink: 0;
                transition: background 0.18s;
            }
            .ct-sw.on { background: #8DC892; }
            .ct-sw.off { background: rgba(255,255,255,0.16); }
            .ct-knob {
                position: absolute; top: 2px; left: 2px;
                width: 18px; height: 18px; border-radius: 50%;
                background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,0.4);
                transition: left 0.18s;
            }
            .ct-sw.on .ct-knob { left: 18px; }

            @media (max-width: 400px) {
                /* Match the Battery tab exactly: stack the hero, keep the base
                   align-items:center so the metrics sit as a content-width block with
                   label-left / value-right rows (not stretched edge-to-edge). */
                .hero { flex-direction: column; gap: 12px; }
                .ev-icon-area { width: 80px; height: 80px; }
            }
        `}getCardSize(){return this._chargers.length>=1?3+2*this._chargers.length:3}static getStubConfig(){return{}}},{type:"sem-ev-status-card",name:"SEM EV Status",description:"Lumina-styled EV charging hero card with per-charger intelligence and settings",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-ev-status-card"});const Ai=["sensor.sem_solar_power","sensor.sem_battery_soc","sensor.sem_autarky_rate","sensor.sem_ev_power","sensor.sem_energy_optimization_score","sensor.sem_energy_tip","sensor.sem_best_surplus_window","sensor.sem_forecast_remaining_today_kwh","sensor.sem_current_vs_peak_percentage","sensor.sem_consecutive_peak_15min","sensor.sem_target_peak_limit","sensor.sem_daily_co2_avoided","sensor.sem_lifetime_co2_avoided"];kt("sem-home-status-card",class extends Lt{static get watchedEntities(){return Ai}static get watchedAttributes(){return{"sensor.sem_target_peak_limit":["peak_limit_unlimited"]}}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||"sensor.sem_"}_val(t,e=null){return At(this._hass?.states[`${this._prefix}${t}`])??e}_valStr(t){const e=this._hass?.states[`${this._prefix}${t}`];return e&&"unavailable"!==e.state&&"unknown"!==e.state?e.state:""}_scoreColor(t){return null==t?"#888":t>=80?"#8DC892":t>=50?"#ff9800":"#f44336"}_peakColor(t){return null==t?"#888":t>90?"#f44336":t>70?"#ff9800":"#8DC892"}_peakStatusKey(t){return t>90?"peak_critical":t>70?"peak_warning":"peak_safe"}_renderChip(t,e,s){return H`
            <div class="chip">
                <ha-icon icon="${t}" style="--mdc-icon-size:16px;color:${e}"></ha-icon>
                <span class="chip-val">${s}</span>
            </div>
        `}render(){if(!this._config||!this._hass)return K;const t=this._val("solar_power",null),e=It(this._val("battery_soc",null)),s=this._val("autarky_rate",null),i=this._val("ev_power"),r=this._val("energy_optimization_score"),a=this._scoreColor(r),n=this._valStr("energy_tip"),o=this._valStr("best_surplus_window")||"—",l=Tt(this._val("forecast_remaining_today_kwh"),1),c=this._val("current_vs_peak_percentage"),d=this._peakColor(c),p=Tt(this._val("consecutive_peak_15min"),1),_=this._hass.states[`${this._prefix}target_peak_limit`],h=jt(_,this._t("uncapped")),u=Ht(_),g=Tt(this._val("daily_co2_avoided"),2),m=Tt(this._val("lifetime_co2_avoided"),1);return H`
            <div class="wrap">

                <!-- 1. Status Chips -->
                <div class="chips-row">
                    ${this._renderChip("mdi:solar-power","#ff9800",null==t?Nt:ut(t))}
                    ${this._renderChip("mdi:battery","#4db6ac",e.label)}
                    ${this._renderChip("mdi:leaf","#8DC892",null==s?Nt:`${s.toFixed(0)}%`)}
                    ${this._renderChip("mdi:car-electric","#8DC892",i>0?ut(i):"—")}
                    <div class="chip">
                        <ha-icon icon="mdi:speedometer" style="--mdc-icon-size:16px;color:${a}"></ha-icon>
                        <span class="chip-val">${Tt(r,0)}</span>
                    </div>
                </div>

                <div class="divider"></div>

                <!-- 2. Smart Tip -->
                <div class="tip-section" style="opacity:${n?"1":"0"};pointer-events:${n?"auto":"none"}">
                    <ha-icon icon="mdi:lightbulb-on-outline"
                             style="--mdc-icon-size:20px;color:#ff9800"></ha-icon>
                    <div class="tip-content">
                        <span class="section-label">${this._t("smart_tip")}</span>
                        <span class="tip-primary">${n||""}</span>
                        <span class="tip-secondary">
                            ${this._t("best_window")}: ${o} &middot; ${this._t("surplus")}: ${l} kWh
                        </span>
                    </div>
                </div>
                <div class="divider" style="opacity:${n?"1":"0"}"></div>

                <!-- 3. Peak Load -->
                <div class="section-label">${this._t("peak_load")}</div>
                <div class="peak-row">
                    <div class="peak-icon-wrap">
                        <ha-icon icon="mdi:flash-alert"
                                 style="--mdc-icon-size:22px;color:#ff9800"></ha-icon>
                        <span class="peak-pct" style="color:${d}">${Tt(c,0)}%</span>
                    </div>
                    <div class="peak-text-wrap">
                        <span class="peak-detail">${p} kW / ${h}${u?"":` (${Tt(c,0)}%)`}</span>
                        <span class="peak-status-badge" style="color:${d};border-color:${d}">
                            ${null==c?Nt:this._t(this._peakStatusKey(c))}
                        </span>
                    </div>
                </div>

                <div class="divider"></div>

                <!-- 5. Environmental Impact -->
                <div class="section-label">${this._t("environmental_impact")}</div>
                <div class="env-row">
                    <div class="env-chip">
                        <ha-icon icon="mdi:leaf"
                                 style="--mdc-icon-size:18px;color:#8DC892"></ha-icon>
                        <div class="env-chip-content">
                            <span class="env-chip-val">${g} ${this._kgUnit("daily_co2_avoided")}</span>
                            <span class="env-chip-label">${this._t("co2_today")}</span>
                        </div>
                    </div>
                    <div class="env-chip">
                        <ha-icon icon="mdi:tree"
                                 style="--mdc-icon-size:18px;color:#8DC892"></ha-icon>
                        <div class="env-chip-content">
                            <span class="env-chip-val">${m} ${this._kgUnit("lifetime_co2_avoided")}</span>
                            <span class="env-chip-label">${this._t("co2_lifetime")}</span>
                        </div>
                    </div>
                </div>

            </div>
        `}static get styles(){return a`
            :host { display: block; }

            .wrap {
                padding: 16px 20px;
                position: relative;
                font-family: 'Segoe UI','Roboto',sans-serif;
                color: var(--primary-text-color, #e0e0e0);
                background:
                    radial-gradient(ellipse 70% 60% at 50% 25%, rgba(91,200,216,0.06) 0%, transparent 100%),
                    radial-gradient(circle at 2px 2px, rgba(128,128,128,0.05) 0.7px, transparent 0.7px);
                background-size: 100% 100%, 50px 50px;
            }

            /* ── Section label ── */
            .section-label {
                font-size: 11px;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.6px;
                color: var(--secondary-text-color, #999);
                margin-bottom: 6px;
            }

            /* ── Divider ── */
            .divider {
                height: 1px;
                background: var(--divider-color, rgba(255,255,255,0.12));
                margin: 12px 0;
            }

            /* ─────────────────── 1. Chips ─────────────────── */
            .chips-row {
                display: flex;
                gap: 6px;
                overflow-x: auto;
                padding-bottom: 4px;
                scrollbar-width: none;
                -ms-overflow-style: none;
            }
            .chips-row::-webkit-scrollbar { display: none; }

            .chip {
                display: inline-flex; align-items: center; gap: 4px;
                padding: 4px 10px;
                border-radius: 12px;
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                background: var(--secondary-background-color, rgba(255,255,255,0.06));
                white-space: nowrap;
                flex-shrink: 0;
                backdrop-filter: blur(16px) saturate(160%);
                -webkit-backdrop-filter: blur(16px) saturate(160%);
            }
            .chip-val {
                font-size: 12px;
                font-weight: 600;
                font-variant-numeric: tabular-nums;
            }

            /* ─────────────────── 2. Tip ─────────────────── */
            .tip-section {
                display: flex; gap: 10px; align-items: flex-start;
                padding: 10px 12px;
                border-radius: 12px;
                background: rgba(255,152,0,0.06);
                border: 1px solid rgba(255,152,0,0.20);
            }
            .tip-section ha-icon { flex-shrink: 0; margin-top: 1px; }
            .tip-content { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
            .tip-primary {
                font-size: 13px; font-weight: 500; line-height: 1.4;
            }
            .tip-secondary {
                font-size: 11px;
                color: var(--secondary-text-color, #999);
                line-height: 1.3;
            }

            /* ─────────────────── 3. Peak ─────────────────── */
            .peak-row {
                display: flex; align-items: center; gap: 10px;
            }
            .peak-icon-wrap {
                display: flex; align-items: center; gap: 6px;
                flex-shrink: 0;
            }
            .peak-pct {
                font-size: 22px; font-weight: 700;
                font-variant-numeric: tabular-nums;
                line-height: 1;
            }
            .peak-text-wrap {
                display: flex; flex-direction: column; gap: 2px;
                min-width: 0;
            }
            .peak-detail {
                font-size: 12px;
                color: var(--secondary-text-color, #999);
                white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
            }
            .peak-status-badge {
                display: inline-block;
                font-size: 11px; font-weight: 600;
                text-transform: uppercase; letter-spacing: 0.4px;
                padding: 2px 7px;
                border-radius: 8px;
                border: 1px solid;
                align-self: flex-start;
            }

            /* ─────────────────── 5. Environmental ─────────────────── */
            .env-row {
                display: flex; gap: 8px; flex-wrap: wrap;
            }
            .env-chip {
                display: flex; align-items: center; gap: 6px;
                padding: 6px 12px;
                border-radius: 12px;
                border: 1px solid rgba(141,200,146,0.25);
                background: rgba(141,200,146,0.06);
                flex: 1; min-width: 120px;
            }
            .env-chip ha-icon { flex-shrink: 0; }
            .env-chip-content { display: flex; flex-direction: column; gap: 0; }
            .env-chip-val {
                font-size: 13px; font-weight: 600;
                font-variant-numeric: tabular-nums;
            }
            .env-chip-label {
                font-size: 11px;
                color: var(--secondary-text-color, #999);
                text-transform: uppercase; letter-spacing: 0.3px;
            }

            @media (max-width: 400px) {
                .env-row { flex-direction: column; }
            }
        `}getCardSize(){return 5}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"sem-home-status-card",name:"SEM Home Status Card",description:"Consolidated status panel for the SEM Home tab",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-home-status-card",preview:!1});const Ti="sensor.sem_tariff_current_import_rate";kt("sem-price-card",class extends Lt{constructor(){super(),this._boundVisibility=()=>{document.hidden||this.requestUpdate()}}connectedCallback(){super.connectedCallback(),document.addEventListener("visibilitychange",this._boundVisibility)}disconnectedCallback(){super.disconnectedCallback(),document.removeEventListener("visibilitychange",this._boundVisibility)}setConfig(t){super.setConfig(t),this._entity=t.entity||Ti,this._compact=!!t.compact}set hass(t){this._hass=t;const e=t?.states[this._entity],s=e?.attributes||{},i=[e?.state,s.price_level,s.next_cheap_start,(s.upcoming||[]).length,this._lang].join("|"),r="function"==typeof semLocalize;(i!==this._lastKey||r&&!this._localizeReady)&&(this._lastKey=i,this._lang=t?.language,this._localizeReady=r,this.requestUpdate())}get hass(){return this._hass}_hm(t){if(!t)return null;const e=this._hass?.config?.time_zone||void 0;try{return new Date(t).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit",timeZone:e})}catch(t){return null}}_levelInfo(t){return{color:Se(t,"#9e9e9e"),key:ke(t)}}render(){if(!this._hass||!this._config)return K;const t=this._hass.states[this._entity];if(!t||"unavailable"===t.state||"unknown"===t.state)return H`<ha-card><div class="wrap empty">${this._t("current_electricity_price")}: —</div></ha-card>`;const e=t.attributes||{};if(!1===e.is_dynamic)return this.style.display="none",K;this.style.display="";const s=parseFloat(t.state),i=e.currency||"",r=this._levelInfo(e.price_level),a=t=>null==t||isNaN(t)?"—":Number(t).toFixed(2),n=Array.isArray(e.upcoming)?e.upcoming:[],o=this._hm(e.next_cheap_start),l=this._hm(e.next_cheap_end);return this._compact?H`
                <ha-card>
                    <div class="chip-row">
                        <span class="chip-title">${this._t("current_electricity_price")}</span>
                        <span class="chip-price" style="color:${r.color}">${a(s)}</span>
                        <span class="chip-unit">${i}/kWh</span>
                        <span class="chip-badge" style="background:${r.color}22;color:${r.color};border-color:${r.color}55">
                            ${this._t(r.key)}
                        </span>
                        ${o?H`<span class="chip-next">${this._t("price_next_cheap")}: <b style="color:#8DC892">${o}</b></span>`:K}
                    </div>
                </ha-card>
            `:H`
            <ha-card>
                <div class="wrap">
                    <div class="head">
                        <span class="title">${this._t("current_electricity_price")}</span>
                        ${e.provider&&"unknown"!==e.provider?H`<span class="prov">${e.provider}</span>`:K}
                    </div>
                    <div class="now">
                        <span class="price" style="color:${r.color}">${a(s)}</span>
                        <span class="unit">${i}/kWh</span>
                        <span class="badge" style="background:${r.color}22;color:${r.color};border-color:${r.color}55">
                            ${this._t(r.key)}
                        </span>
                    </div>
                    <div class="summary">
                        <span>${this._t("today")}: <b>min ${a(e.today_min)}</b> · avg ${a(e.today_avg)} · <b>max ${a(e.today_max)}</b></span>
                        ${o?H`<span class="cheap">${this._t("price_next_cheap")}: <b>${o}${l?"–"+l:""}</b></span>`:K}
                    </div>
                    ${n.length>=2?this._renderStrip(n):K}
                </div>
            </ha-card>
        `}_renderStrip(t){const e=Date.now(),s=t.map(t=>({t:new Date(t.t).getTime(),price:t.price,level:t.level})).filter(t=>!isNaN(t.t)).sort((t,e)=>t.t-e.t).filter(t=>t.t>=e-36e5).slice(0,24);if(s.length<2)return K;const i=s.map(t=>t.price),r=Math.min(...i),a=Math.max(...i)-r||1,n=s.length,o=(320-2*(n-1))/n,l=s.map((t,s)=>{const i=6+52*((t.price-r)/a),n=s*(o+2),l=64-i,c=this._levelInfo(t.level).color,d=t.t<=e&&e<t.t+36e5;return j`<rect x="${n}" y="${l}" width="${o}" height="${i}" rx="1.5"
                fill="${c}" opacity="${d?"1":"0.65"}"
                stroke="${d?"#fff":"none"}" stroke-width="${d?"1":"0"}"/>`}),c=s.map((t,e)=>{if(e%6!=0)return K;const s=e*(o+2)+o/2,i=new Date(t.t).getHours();return j`<text x="${s}" y="${75}" text-anchor="middle"
                fill="var(--secondary-text-color,#999)" font-size="9">${String(i).padStart(2,"0")}</text>`});return H`
            <svg class="strip" viewBox="0 0 ${320} ${78}" width="100%" preserveAspectRatio="none">
                ${l}${c}
            </svg>
        `}getCardSize(){return 2}static getStubConfig(){return{entity:Ti}}static get styles(){return a`
            ha-card { background: var(--ha-card-background, var(--card-background-color)); }
            .wrap { padding: 12px 14px; }
            .wrap.empty { color: var(--secondary-text-color,#999); }
            .head { display: flex; align-items: baseline; gap: 8px; }
            .title { font-size: 13px; font-weight: 600; color: var(--primary-text-color,#e0e0e0); }
            .prov { margin-left: auto; font-size: 12px; color: var(--secondary-text-color,#999); text-transform: capitalize; }
            .now { display: flex; align-items: baseline; gap: 8px; margin: 4px 0 6px; }
            .price { font-size: 30px; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1; }
            .unit { font-size: 12px; color: var(--secondary-text-color,#999); }
            .badge { margin-left: auto; font-size: 12px; font-weight: 600; padding: 2px 9px;
                     border-radius: 10px; border: 1px solid; text-transform: capitalize; }
            .summary { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 12px;
                       color: var(--secondary-text-color,#aaa); margin-bottom: 8px; }
            .summary b { color: var(--primary-text-color,#e0e0e0); font-variant-numeric: tabular-nums; }
            .summary .cheap b { color: #8DC892; }
            .strip { display: block; overflow: visible; }
            .static-note { font-size: 12px; color: var(--secondary-text-color,#999); padding-top: 2px; }
            /* Compact chip (#257, compact: true) — one row, glance-only. */
            .chip-row {
                display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
                padding: 8px 14px;
            }
            .chip-title { font-size: 12px; font-weight: 600; color: var(--primary-text-color,#e0e0e0); }
            .chip-price { font-size: 17px; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1; }
            .chip-unit { font-size: 12px; color: var(--secondary-text-color,#999); }
            .chip-badge { font-size: 11px; font-weight: 600; padding: 1px 8px;
                          border-radius: 9px; border: 1px solid; text-transform: capitalize; }
            .chip-next { margin-left: auto; font-size: 12px; color: var(--secondary-text-color,#aaa); }
            .chip-next b { font-variant-numeric: tabular-nums; }
        `}},{type:"sem-price-card",name:"SEM Price Card",description:"Dynamic electricity price: current price, level, today range, next cheap window, and an hourly price strip (#257)",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-price-card",preview:!1});const Ii=[{id:"info",icon:"mdi:information-outline",color:"#96CAEE",titleKey:"system_info",subtitleFn:t=>`v${t._val("diag_version")||"—"} · ${t._valLabel("diag_grid_mode")||"—"}`},{id:"health",icon:"mdi:heart-pulse",color:"#8DC892",titleKey:"health_overview",subtitleFn:t=>{const e=t._valFmt("solar_power"),s=t._valFmt("battery_soc");return`${e}W ${t._t("solar")} · SOC ${s}%`}},{id:"diag",icon:"mdi:bug-outline",color:"#ff9800",titleKey:"diagnostics",subtitleFn:()=>""}],Ri=[{key:"solar_power",icon:"mdi:solar-power",color:"#ff9800",suffix:"W"},{key:"grid_power",icon:"mdi:transmission-tower",color:"#488fc2",suffix:"W"},{key:"battery_soc",icon:"mdi:battery",color:"#4db6ac",suffix:"%"},{key:"forecast_today_kwh",icon:"mdi:weather-sunny",color:"#ff9800",suffix:"kWh"},{key:"tariff_current_import_rate",icon:"mdi:tag",color:"#96CAEE",suffix:""}],Bi=["sensor.sem_diag_version","sensor.sem_diag_grid_mode","sensor.sem_diag_battery_capacity","sensor.sem_diag_update_interval","sensor.sem_diag_charger_count","sensor.sem_diag_charger_control","sensor.sem_diag_sensors_unavailable","sensor.sem_diag_ed_config","sensor.sem_solar_power","sensor.sem_grid_power","sensor.sem_battery_soc","sensor.sem_ev_power","sensor.sem_forecast_today_kwh","sensor.sem_tariff_current_import_rate","switch.sem_observer_mode","sensor.sem_home_consumption_power","sensor.sem_grid_import_power","sensor.sem_grid_export_power","sensor.sem_autarky_rate","sensor.sem_self_consumption_rate","sensor.sem_battery_power","sensor.sem_night_charging_status","sensor.sem_battery_status","sensor.sem_grid_status","sensor.sem_charging_state"];kt("sem-system-card",class extends Lt{static get watchedEntities(){return Bi}constructor(){super(),this._collapsed={info:!1,health:!1,diag:!0},this._copyFeedback=""}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||"sensor.sem_"}_val(t){const e=this._hass?.states[`${this._prefix}${t}`];return e&&"unavailable"!==e.state&&"unknown"!==e.state?e.state:""}_valFmt(t,e=0){return function(t,e=0){return Ft(t)?Nt:parseFloat(t.state).toFixed(e)}(this._hass?.states[`${this._prefix}${t}`],e)}_valNum(t,e=null){return At(this._hass?.states[`${this._prefix}${t}`])??e}_switchOn(t){return"on"===this._hass?.states[`switch.sem_${t}`]?.state}_available(t){const e=this._hass?.states[t];return!(!e||"unavailable"===e.state||"unknown"===e.state)}_toggleSection(t){this._collapsed={...this._collapsed,[t]:!this._collapsed[t]},this.requestUpdate()}_copyDiagnostics(){const t=this._val("diag_version")||"—",e=this._val("diag_grid_mode")||"—",s=this._val("diag_charger_count")||"—",i=this._val("diag_charger_control")||"—",r=this._valNum("diag_battery_capacity"),a=`SEM ${t} | Grid: ${e} | Chargers: ${s} (${i}) | Battery: ${r>0?r.toFixed(1):"—"}kWh | Unavailable: ${this._val("diag_sensors_unavailable")||Nt}`,n=this._hass?.states?.["sensor.sem_diag_ed_config"]?.attributes?.energy_dashboard;let o;if(n){const t=t=>t||"—";o=`Solar:   pwr=${t(n.solar?.power)} [${t(n.solar?.power_source)}]  energy=${t(n.solar?.energy)}\nGrid:    pwr=${t(n.grid?.power)} [${t(n.grid?.power_source)}]  imp=${t(n.grid?.import_energy)}  exp=${t(n.grid?.export_energy)}\nBattery: pwr=${t(n.battery?.power)} [${t(n.battery?.power_source)}]  chg=${t(n.battery?.charge_energy)}  dis=${t(n.battery?.discharge_energy)}`}else o=`Config: ${this._val("diag_ed_config")||"—"}`;const l=`${a}\n${o}`;this._writeClipboard(l)}async _writeClipboard(t){const e=t=>{this._copyFeedback=this._t(t),this.requestUpdate(),setTimeout(()=>{this._copyFeedback="",this.requestUpdate()},2e3)};if(navigator?.clipboard?.writeText&&!1!==window.isSecureContext)try{return await navigator.clipboard.writeText(t),void e("copied")}catch(t){console.warn("[SEM System] modern clipboard API failed, falling back to execCommand",t)}try{const s=document.createElement("textarea");s.value=t,s.setAttribute("readonly",""),s.style.position="fixed",s.style.top="0",s.style.left="0",s.style.width="1px",s.style.height="1px",s.style.opacity="0",document.body.appendChild(s),s.focus(),s.select();const i=document.execCommand("copy");document.body.removeChild(s),i?e("copied"):(e("copy_failed"),console.error('[SEM System] execCommand("copy") returned false'))}catch(t){e("copy_failed"),console.error("[SEM System] legacy clipboard fallback threw",t)}}_renderSectionHeader(t,e){const s=this._collapsed[t.id],i=s?"rotate(-90deg)":"rotate(0deg)";return H`
            <div
                class="section-header"
                tabindex="0"
                role="button"
                aria-expanded="${!s}"
                @click=${()=>this._toggleSection(t.id)}
                @keydown=${e=>{"Enter"!==e.key&&" "!==e.key||(e.preventDefault(),this._toggleSection(t.id))}}
            >
                <ha-icon icon="${t.icon}" style="--mdc-icon-size:20px;color:${t.color}"></ha-icon>
                <span class="section-title-text">${this._t(t.titleKey)}</span>
                <span class="section-subtitle">${t.subtitleFn(this)}</span>
                <ha-icon
                    class="chevron"
                    icon="mdi:chevron-down"
                    style="--mdc-icon-size:18px;transform:${i}"
                ></ha-icon>
            </div>
        `}_renderInfoSection(t){const e=this._valNum("diag_battery_capacity"),s=this._valNum("diag_update_interval"),i=this._val("diag_charger_count")||"—",r=this._valLabel("diag_charger_control"),a=r?`${i} (${r})`:i;return H`
            <div class="info-row">
                <span class="info-row-label">${this._t("version")}</span>
                <span class="info-row-value">${this._val("diag_version")||"—"}</span>
            </div>
            <div class="info-row">
                <span class="info-row-label">${this._t("grid_mode")}</span>
                <span class="info-row-value">${this._valLabel("diag_grid_mode")||"—"}</span>
            </div>
            <div class="info-row">
                <span class="info-row-label">${this._t("battery_capacity")}</span>
                <span class="info-row-value">${e>0?e.toFixed(1)+" kWh":"—"}</span>
            </div>
            <div class="info-row">
                <span class="info-row-label">${this._t("update_interval")}</span>
                <span class="info-row-value">${s>0?s.toFixed(0)+" s":"—"}</span>
            </div>
            <div class="info-row">
                <span class="info-row-label">${this._t("chargers")}</span>
                <span class="info-row-value">${a}</span>
            </div>
            <div class="info-row">
                <span class="info-row-label">${this._t("unavailable_sensors")}</span>
                <span class="info-row-value">${this._val("diag_sensors_unavailable")||Nt}</span>
            </div>
        `}_renderHealthSection(t){return H`
            <div class="health-chips">
                ${Ri.map(t=>{const e=`${this._prefix}${t.key}`,s=this._available(e),i=this._hass?.states[e],r=i?i.state:"—";let a=t.suffix;if("tariff_current_import_rate"===t.key){const t=i?.attributes?.currency;a=t?` ${t}/kWh`:""}return H`
                        <div class="health-chip" style="background:${s?"rgba(141,200,146,0.12)":"rgba(244,67,54,0.12)"};border:1px solid ${s?"rgba(141,200,146,0.3)":"rgba(244,67,54,0.3)"}">
                            <ha-icon icon="${t.icon}" style="--mdc-icon-size:16px;color:${t.color}"></ha-icon>
                            <span class="chip-value">${s?`${r}${a}`:"—"}</span>
                        </div>
                    `})}
            </div>
        `}_renderToggle(t,e,s){const i="on"===this._hass?.states[t]?.state;return H`
            <div class="toggle-row">
                <span class="toggle-label">${this._t(e)}</span>
                <div
                    class="toggle-track ${i?"on":""}"
                    @click=${()=>this._toggleSwitch(t)}
                >
                    <div class="toggle-thumb"></div>
                </div>
            </div>
        `}_renderDiagBlock(t,e){return H`
            <div class="diag-block">
                <span class="diag-block-label">${this._t(t)}</span>
                <span class="diag-block-text">${e}</span>
            </div>
        `}_renderDiagSection(t){const e=`Solar ${this._valFmt("solar_power")}W · Grid ${this._valFmt("grid_power")}W · Battery ${this._valFmt("battery_power")}W · SOC ${this._valFmt("battery_soc")}% · EV ${this._valFmt("ev_power")}W`,s=`Home ${this._valFmt("home_consumption_power")}W · Import ${this._valFmt("grid_import_power")}W · Export ${this._valFmt("grid_export_power")}W · Autarky ${this._valFmt("autarky_rate")}% · Self ${this._valFmt("self_consumption_rate")}%`,i=this._val("charging_state")||"—",r=this._val("night_charging_status")||"—",a=this._val("battery_status")||"—",n=this._val("grid_status")||"—",o=`${i} · ${this._t("night")}: ${r} · ${this._t("battery")}: ${a} · ${this._t("grid")}: ${n}`;return H`
            ${this._renderDiagBlock("source_sensors",e)}
            ${this._renderDiagBlock("derived_values",s)}
            ${this._renderDiagBlock("mode_status",o)}
        `}_renderSection(t,e,s){const i=this._collapsed[t.id];return H`
            <div class="section">
                ${this._renderSectionHeader(t,s)}
                <div class="section-content ${i?"":"expanded"}">
                    <div class="section-body">
                        ${e(s)}
                    </div>
                </div>
            </div>
        `}render(){if(!this._config)return K;const t=this._theme(),e=!1!==t.isDark,s=t.accent||"#42a5f5",i={info:t=>this._renderInfoSection(t),health:t=>this._renderHealthSection(t),diag:t=>this._renderDiagSection(t)};return H`
            <style>
                :host { display: block; contain: layout style paint; }
                .wrap {
                    padding: 16px 20px;
                    position: relative;
                    background: ${vt(t,pt.inverter)};
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${t.text});
                }

                /* ── Sections ── */
                .section {
                    margin-bottom: 8px;
                    border-radius: 14px;
                    background: ${t.surface};
                    border: 1px solid ${t.surfaceBorder};
                    overflow: hidden;
                    transition: border-color 0.2s;
                }
                .section:hover { border-color: ${e?"rgba(255,255,255,0.18)":"rgba(0,0,0,0.12)"}; }

                .section-header {
                    display: flex; align-items: center; gap: 8px;
                    padding: 12px 14px;
                    cursor: pointer;
                    user-select: none;
                    -webkit-user-select: none;
                    transition: background 0.15s;
                }
                .section-header:hover { background: ${t.surfaceHover}; }
                .section-title-text {
                    font-size: 14px; font-weight: 600;
                    white-space: nowrap;
                }
                .section-subtitle {
                    flex: 1;
                    font-size: 12px;
                    color: var(--secondary-text-color, ${t.textSec});
                    text-align: right;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    margin-right: 4px;
                }
                .chevron {
                    transition: transform 0.25s ease;
                    color: var(--secondary-text-color, ${t.textSec});
                    flex-shrink: 0;
                }

                /* ── Collapsible content ── */
                .section-content {
                    max-height: 0;
                    opacity: 0;
                    overflow: hidden;
                    transition: max-height 0.3s ease, opacity 0.2s ease;
                }
                .section-content.expanded {
                    max-height: 1000px;
                    opacity: 1;
                }
                .section-body {
                    padding: 0 14px 14px;
                }

                /* ── Info rows ── */
                .info-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 7px 0;
                    border-bottom: 1px solid ${t.surfaceBorder};
                }
                .info-row:last-child { border-bottom: none; }
                .info-row-label {
                    font-size: 13px; font-weight: 500;
                    color: var(--secondary-text-color, ${t.textSec});
                }
                .info-row-value {
                    font-size: 13px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }

                /* ── Health chips ── */
                .health-chips {
                    display: flex; flex-wrap: wrap; gap: 8px;
                    padding: 8px 0 4px;
                }
                .health-chip {
                    display: flex; align-items: center; gap: 6px;
                    padding: 6px 10px;
                    border-radius: 20px;
                    transition: background 0.2s, border-color 0.2s;
                }
                .chip-value {
                    font-size: 12px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }

                /* ── Toggle ── */
                .toggle-group { padding-top: 2px; }
                .toggle-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 9px 0;
                    border-bottom: 1px solid ${t.surfaceBorder};
                }
                .toggle-row:last-child { border-bottom: none; }
                .toggle-label { font-size: 13px; font-weight: 500; }
                .toggle-track {
                    position: relative;
                    width: 42px; height: 24px;
                    border-radius: 12px;
                    background: ${e?"rgba(255,255,255,0.15)":"rgba(0,0,0,0.18)"};
                    cursor: pointer;
                    transition: background 0.2s;
                    flex-shrink: 0;
                }
                .toggle-track.on { background: ${s}; }
                .toggle-thumb {
                    position: absolute;
                    top: 2px; left: 2px;
                    width: 20px; height: 20px;
                    border-radius: 50%;
                    background: white;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.3);
                    transition: left 0.2s;
                }
                .toggle-track.on .toggle-thumb { left: 20px; }

                /* ── Diagnostics ── */
                .diag-block {
                    padding: 8px 0;
                    border-bottom: 1px solid ${t.surfaceBorder};
                }
                .diag-block:last-child { border-bottom: none; }
                .diag-block-label {
                    display: block;
                    font-size: 11px; font-weight: 600;
                    text-transform: uppercase;
                    letter-spacing: 0.4px;
                    color: var(--secondary-text-color, ${t.textSec});
                    margin-bottom: 3px;
                }
                .diag-block-text {
                    display: block;
                    font-size: 12px; font-weight: 500;
                    line-height: 1.5;
                    word-break: break-word;
                    font-variant-numeric: tabular-nums;
                }

                /* ── Copy button ── */
                .copy-row {
                    margin-top: 10px;
                    display: flex; flex-direction: column; align-items: center; gap: 4px;
                }
                .copy-btn {
                    display: flex; align-items: center; gap: 6px;
                    padding: 8px 18px;
                    border-radius: 10px;
                    border: 1px solid ${t.surfaceBorder};
                    background: ${t.surface};
                    color: var(--primary-text-color, ${t.text});
                    font-size: 13px; font-weight: 600;
                    font-family: inherit;
                    cursor: pointer;
                    transition: background 0.15s, border-color 0.15s;
                }
                .copy-btn:hover { background: ${t.surfaceHover}; border-color: #96CAEE; }
                .copy-btn:active { background: ${e?"rgba(255,255,255,0.15)":"rgba(0,0,0,0.08)"}; }
                .copy-feedback {
                    font-size: 11px;
                    color: #8DC892;
                    min-height: 16px;
                    transition: opacity 0.3s;
                    opacity: ${this._copyFeedback?"1":"0"};
                }

                @media (max-width: 480px) {
                    .health-chips { gap: 6px; }
                    .health-chip { padding: 5px 8px; }
                }
            </style>
            <div class="wrap">
                ${Ii.map(e=>this._renderSection(e,i[e.id],t))}
                <div class="copy-row">
                    <button class="copy-btn" @click=${()=>this._copyDiagnostics()}>
                        <ha-icon icon="mdi:content-copy" style="--mdc-icon-size:16px"></ha-icon>
                        ${this._t("copy_diagnostics")}
                    </button>
                    <span class="copy-feedback">${this._copyFeedback}</span>
                </div>
            </div>
        `}getCardSize(){return 8}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"sem-system-card",name:"SEM System Card",description:"Integration health — version, detected hardware, grid mode, sensor availability",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-system-card",preview:!1});const Oi={now:{icon:"mdi:clock-outline",color:"#5BC8D8"},solar_peak:{icon:"mdi:weather-sunny",color:"#ff9800"},solar_end:{icon:"mdi:weather-sunset",color:"#ff9800"},cheap_start:{icon:"mdi:arrow-down-bold",color:"#8DC892"},cheap_end:{icon:"mdi:arrow-up-bold",color:"#ff9800"},expensive_start:{icon:"mdi:flash-alert",color:"#f06292"},expensive_end:{icon:"mdi:flash-off",color:"#8DC892"},night_open:{icon:"mdi:weather-night",color:"#8353d1"},night_end:{icon:"mdi:weather-sunset-up",color:"#ff9800"},ev_charge_start:{icon:"mdi:ev-station",color:"#8DC892"},ev_min_reached:{icon:"mdi:battery-charging-80",color:"#4db6ac"},ev_target_reached:{icon:"mdi:car-electric",color:"#8DC892"},ev_deadline:{icon:"mdi:clock-end",color:"#f06292"},ev_wait:{icon:"mdi:pause-circle",color:"#8353d1"},battery_full:{icon:"mdi:battery-charging-100",color:"#f06292"},battery_empty:{icon:"mdi:battery-low",color:"#4db6ac"},device_run:{icon:"mdi:power-plug",color:"#5BC8D8"},device_done:{icon:"mdi:check-circle",color:"#8DC892"},export_closed:{icon:"mdi:transmission-tower-off",color:"#f06292"},export_reopens:{icon:"mdi:transmission-tower",color:"#8353d1"}};kt("sem-today-plan-card",class extends Lt{setConfig(t){super.setConfig(t),this._entity=t.entity||"sensor.sem_charging_state"}set hass(t){this._hass=t;const e=(t?.states[this._entity]?.attributes||{}).today_plan||[],s=[e.length,e[0]?.when,e.at(-1)?.when,this._lang].join("|"),i="function"==typeof semLocalize;(s!==this._lastKey||i&&!this._localizeReady)&&(this._lastKey=s,this._lang=t?.language,this._localizeReady=i,this.requestUpdate())}get hass(){return this._hass}_hm(t){if(!t)return"—";try{const e=new Date(t),s=this._hass?.config?.time_zone||void 0,i=gt(t,s),r=t=>t.toLocaleDateString("en-CA",{timeZone:s}),a=r(e),n=new Date;if(a===r(n))return i;if(a===r(new Date(n.getTime()+864e5))){return`${this._t("tomorrow")||"Tomorrow"} ${i}`}return`${e.toLocaleDateString([],{weekday:"short",timeZone:s})} ${i}`}catch(t){return"—"}}_format(t,e){let s=this._t(t);if(!s||s===t)return null;for(const[t,i]of Object.entries(e||{}))s=s.replace(new RegExp(`\\{${t}\\}`,"g"),i);return s}render(){if(!this._hass||!this._config)return K;const t=this._hass.states[this._entity],e=t?.attributes?.today_plan||[];return!Array.isArray(e)||e.length<=1?(this.style.display="none",K):(this.style.display="",H`
            <ha-card>
                <div class="wrap">
                    <div class="head">
                        <ha-icon icon="mdi:calendar-clock" style="--mdc-icon-size:16px;color:#5BC8D8"></ha-icon>
                        <span class="title">${this._t("today_plan_title")}</span>
                    </div>
                    <ul class="rows">
                        ${e.map(t=>{const e=Oi[t.kind]||Oi.now,s=this._format(t.label,t.values)||t.label,i=t.detail?this._format(t.detail,t.values):null;return H`
                                <li class="row ${"now"===t.kind?"now":""}">
                                    <span class="time">${this._hm(t.when)}</span>
                                    <ha-icon icon="${e.icon}" style="--mdc-icon-size:14px;color:${e.color}"></ha-icon>
                                    <div class="text">
                                        <span class="label">${s}</span>
                                        ${i?H`<span class="detail">${i}</span>`:K}
                                    </div>
                                </li>
                            `})}
                    </ul>
                </div>
            </ha-card>
        `)}static get styles(){return a`
            :host { display: block; }
            ha-card {
                background: var(--card-background-color, #1e232d);
                backdrop-filter: blur(16px) saturate(160%);
                -webkit-backdrop-filter: blur(16px) saturate(160%);
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 14px;
            }
            .wrap { padding: 12px 14px; }
            .head {
                display: flex; align-items: center; gap: 6px;
                margin-bottom: 8px;
                opacity: 0.85;
            }
            .title {
                font-size: 12px; letter-spacing: 0.04em; text-transform: uppercase;
                color: var(--primary-text-color);
            }
            .rows { list-style: none; padding: 0; margin: 0; }
            .row {
                display: grid;
                grid-template-columns: 64px 18px 1fr;
                align-items: center; gap: 10px;
                padding: 5px 0;
                font-size: 13px;
                color: var(--primary-text-color);
                border-bottom: 1px dashed rgba(255,255,255,0.04);
            }
            .row:last-child { border-bottom: none; }
            .row.now {
                background: linear-gradient(90deg, rgba(91,200,216,0.10), transparent);
                margin-left: -4px; padding-left: 4px;
                border-radius: 4px;
            }
            .time {
                font-variant-numeric: tabular-nums;
                font-weight: 600;
                color: var(--secondary-text-color);
                font-size: 12px;
            }
            .text { display: flex; flex-direction: column; min-width: 0; }
            .label { font-weight: 500; line-height: 1.2; }
            .detail {
                font-size: 11px; opacity: 0.65; line-height: 1.2;
            }
        `}},{type:"sem-today-plan-card",name:"SEM Today's Plan",description:"Forward-looking schedule combining tariff, solar, and EV",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-today-plan-card"});const Li={ev:{icon:"mdi:ev-station",color:"#8DC892",label:"energy_plan_kind_ev"},load:{icon:"mdi:power-plug",color:"#5BC8D8",label:"energy_plan_kind_load"},battery:{icon:"mdi:home-battery",color:"#f06292",label:"energy_plan_kind_battery"},comfort:{icon:"mdi:thermometer",color:"#4db6ac",label:"energy_plan_kind_comfort"}},Pi=Object.fromEntries(Object.entries(Li).map(([t,e])=>[t,e.label])),Ui={actuation:{docs:"https://github.com/traktore-org/sem-community/blob/develop/docs/ENERGY_PLANNER.md#actuation-g4"},arbitrage:{docs:"https://github.com/traktore-org/sem-community/blob/develop/docs/ENERGY_PLANNER.md#the-arbitrage-advisor"}},Wi={fits:{icon:"mdi:check-circle",color:"#8DC892"},partial:{icon:"mdi:circle-slice-4",color:"#ff9800"},yields:{icon:"mdi:alert-circle-outline",color:"#f06292"}};class Hi extends Lt{setConfig(t){super.setConfig(t),this._entity=t.entity||"sensor.sem_energy_plan"}set hass(t){this._hass=t;const e=t?.states[this._entity],s=e?.attributes||{},i=!0===s.actuation&&Array.isArray(s.demands)?s.demands.map(t=>this._liveState(t,s.blocks)).join(","):"",r=s.tomorrow||{},a=s.coverage?Object.entries(s.coverage).map(([t,e])=>t+"="+e).join(","):"",n=[e?.state,s.computed_at,s.actuation,i,a,this._view||"today",r.prices,r.forecast_kwh,r.stamps_at,t?.states["switch.sem_energy_plan_actuation"]?.state,t?.states["sensor.sem_night_start_time"]?.state,t?.language].join("|"),o="function"==typeof semLocalize;(n!==this._lastKey||o&&!this._localizeReady)&&(this._lastKey=n,this._lang=t?.language,this._localizeReady=o,this.requestUpdate())}get hass(){return this._hass}_liveState(t,e){if(!t||"battery"===t.kind)return null;if("fits"!==t.status)return"reactive";const s=Date.now();let i=null,r=!1;for(const a of Array.isArray(e)?e:[]){if(a.id!==t.id)continue;const e=Date.parse(a.start),n=Date.parse(a.end);if(Number.isFinite(e)&&Number.isFinite(n)){if(r=!0,e<=s&&s<n)return"now";e>s&&(null===i||e<i)&&(i=e)}}return null!==i?"wait:"+i:r?"done":null}_covKey(t){if(!t||"covered"===t)return null;if(t.startsWith("verdict"))return"energy_plan_cov_yields";return{"no plan":"energy_plan_cov_no_plan","stale stamp":"energy_plan_cov_stale","outside span":"energy_plan_cov_outside","not in plan":"energy_plan_cov_not_in_plan","actuation off":"energy_plan_cov_actuation_off","nothing planned":"energy_plan_cov_nothing_planned"}[t]||"energy_plan_cov_unreadable"}_covChip(t){const e=this._covKey(t);return e?H`<span class="chip chip-reactive"
            title="${this._t("energy_plan_reactive_tip")} — ${this._t(e)}"
            >${this._t("energy_plan_reactive")} · ${this._t(e)}</span>`:K}_liveChip(t){if(!t)return K;if("now"===t)return H`<span class="live now">▶ ${this._t("energy_plan_live_now")}</span>`;if(t.startsWith("wait:")){const e=this._hm(new Date(Number(t.slice(5))).toISOString());return H`<span class="live wait">${this._format("energy_plan_live_wait",{time:e})||e}</span>`}return"done"===t?H`<span class="live done">${this._t("energy_plan_live_done")}</span>`:H`<span class="live react">${this._t("energy_plan_live_reactive")}</span>`}_hm(t){return t?gt(t,this._hass?.config?.time_zone||void 0):"—"}_demandName(t,e,s){return function(t,e,s,i,r){if(t)return t;const a=String(e||"").split(":")[0];return r(i[s]||i[a]||i.load)}(t,e,s,Pi,t=>this._t(t))}_format(t,e){let s=this._t(t);if(!s||s===t)return null;for(const[t,i]of Object.entries(e||{}))s=s.replace(new RegExp("\\{"+t+"\\}","g"),i);return s}_runs(t,e,s,i){const r=[];for(const[e,s]of t.entries()){const t=i(s,e),a=Date.parse(s.start),n=Date.parse(s.end);if(!Number.isFinite(a)||!Number.isFinite(n))continue;const o=r[r.length-1];o&&o.v===t&&Math.abs(o.endMs-a)<1e3?o.endMs=n:r.push({v:t,startMs:a,endMs:n})}return r.map(t=>({v:t.v,left:(t.startMs-e)/s*100,width:(t.endMs-t.startMs)/s*100}))}_modeChip(t){return H`<span class="chip ${t?"chip-active":""}"
            title="${this._t(t?"energy_plan_active_note":"energy_plan_shadow_note")}">${this._t(t?"energy_plan_active":"energy_plan_shadow")}</span>`}_docsLink(t="actuation"){return H`<a class="docs-link" href="${Ui[t].docs}" target="_blank"
            rel="noopener" title="${this._t("config_docs")}">
            <ha-icon icon="mdi:book-open-variant" style="--mdc-icon-size:13px"></ha-icon>
        </a>`}_viewToggle(t){if(!t)return K;const e=this._view||"today",s=(t,s)=>H`
            <button class="vbtn ${e===t?"vbtn-on":""}"
                @click=${()=>{this._view=t,this.requestUpdate()}}>
                ${this._t(s)}</button>`;return H`<span class="vtoggle">
            ${s("today","energy_plan_today")}${s("tomorrow","energy_plan_tomorrow")}
        </span>`}_renderTomorrow(t){const e=t.provisional||null,s=Date.parse(t.stamps_at),i=Date.parse(t.night_open),r=i-s,a=Number.isFinite(r)&&r>0,n=t=>(Date.parse(t)-s)/r*100,o=(t,e,s)=>{const i=Math.max(0,n(t.start)),r=Math.min(100,n(t.end))-i;return!Number.isFinite(i)||!Number.isFinite(r)||r<=0?K:H`<div class="seg ${e}" style="left:${i}%;width:${Math.max(r,1.2)}%${s?`;background:${s}`:""}"></div>`},l=H`
            <div class="band">
                ${(t.surplus_windows||[]).map(t=>o(t,"tmw-sun"))}
                ${(t.cheap_windows||[]).map(t=>o(t,"cheap"))}
            </div>
        `,c=H`
            <div class="band">
                ${(t.cheap_windows||[]).map(t=>o(t,"cheap"))}
            </div>
        `,d=[];if(a){const t=new Date(s);t.setMinutes(0,0,0),t.getTime()<s&&t.setHours(t.getHours()+1);const e=Math.max(2,Math.ceil(r/36e5/5));for(let a=new Date(t);a.getTime()<i;a.setHours(a.getHours()+e)){const t=(a.getTime()-s)/r*100;if(t>94)break;d.push({left:t,text:this._hm(a.toISOString())})}}const p=e&&Array.isArray(e.soc_curve)?e.soc_curve:[],_=[];for(let t=0;t+1<p.length;t++)_.push({start:p[t].t,end:p[t+1].t,rising:p[t+1].kwh>p[t].kwh+.01});const h=t.known_asks||[],u="final"!==t.prices;return H`
            <ha-card>
                <div class="wrap">
                    <div class="head">
                        <ha-icon icon="mdi:weather-night" style="--mdc-icon-size:16px;color:#8353d1"></ha-icon>
                        <span class="title">${this._t("energy_plan_title")}</span>
                        ${this._viewToggle(!0)}
                        <span class="chip" title="${this._t("energy_plan_provisional_tip")}">${this._t("energy_plan_provisional")}</span>
                        <span class="chip ${u?"":"chip-active"}"
                              title="${this._t(u?"energy_plan_prices_preliminary_tip":"energy_plan_prices_final_tip")}">
                            ${this._t(u?"energy_plan_prices_preliminary":"energy_plan_prices_final")}</span>
                        ${this._docsLink()}
                    </div>
                    <div class="strip ${a?"":"nostrip"}">
                        ${a?H`
                            <div class="lbl axis"></div>
                            <div class="track axis">
                                ${c}
                                ${d.map(t=>H`
                                    <span class="tick ${t.left<4?"first":""}" style="left:${t.left}%">${t.text}</span>
                                `)}
                            </div>
                            <div class="stat axis"></div>
                        `:K}
                        ${p.length>1?H`
                            <div class="lbl" title="${this._t("energy_plan_provisional_tip")}">
                                <div class="lname">
                                    <ha-icon icon="mdi:home-battery" style="--mdc-icon-size:13px;color:#4db6ac"></ha-icon>
                                    <span class="name">${this._t("energy_plan_kind_battery")}</span>
                                </div>
                            </div>
                            ${a?H`
                                <div class="track">
                                    ${l}
                                    ${_.map(t=>o(t,"run",t.rising?"#f06292":"#4db6ac"))}
                                </div>
                            `:K}
                            <div class="stat">
                                <span>${p[0].kwh.toFixed(1)} → ${p[p.length-1].kwh.toFixed(1)} kWh</span>
                            </div>
                        `:K}
                        ${h.map((t,s)=>{const i=Li[t.kind]||Li.load,r=((t,s)=>e&&Array.isArray(e.blocks)?e.blocks.filter(e=>e.id===`${t}:${s}`):[])(t.kind,s),n=[this._demandName(t.label,null,t.kind),r.map(t=>`${this._hm(t.start)}–${this._hm(t.end)}`).join("\n")||null,this._t("energy_plan_provisional_tip")].filter(Boolean).join("\n");return H`
                                <div class="lbl" title="${n}">
                                    <div class="lname">
                                        <ha-icon icon="${i.icon}" style="--mdc-icon-size:13px;color:${i.color}"></ha-icon>
                                        <span class="name">${this._demandName(t.label,null,t.kind)}</span>
                                    </div>
                                </div>
                                ${a?H`
                                    <div class="track">
                                        ${l}
                                        ${r.map(t=>o(t,"run",i.color))}
                                    </div>
                                `:K}
                                <div class="stat">
                                    <span>${(t.kwh||0).toFixed(1)} kWh</span>
                                </div>
                            `})}
                    </div>
                    <div class="legend">
                        <span class="key"><i class="sw tmw-sun-key"></i>${this._t("energy_plan_legend_surplus")}</span>
                        <span class="key"><i class="sw cheapkey"></i>${this._t("energy_plan_legend_cheap")}</span>
                        ${p.length>1?H`<span class="key"><i class="sw" style="background:#f06292"></i>${this._t("energy_plan_legend_battery_charge")}</span>`:K}
                    </div>
                    <div class="idle">
                        ☀ ${(t.forecast_kwh||0).toFixed(1)} kWh ·
                        ${this._format("energy_plan_stamps_at",{time:this._hm(t.stamps_at)})}
                    </div>
                </div>
            </ha-card>
        `}_renderReview(){const t=this._hass?.states?.[this._entity]?.attributes?.review;if(!t)return K;const e=[];for(const s of t.demands||[]){const t=this._format("energy_plan_review_"+s.code,{nights:s.nights,asked:(s.asked_kwh||0).toFixed(1),suggested:null==s.suggested_kwh?"":Number(s.suggested_kwh).toFixed(1),actual:(s.last_kwh||0).toFixed(1)});t&&e.push({d:s,text:t,k:Li[s.kind]||Li.load})}const s=t.battery,i=s?this._format("energy_plan_review_"+s.code,{drained:(s.drained||0).toFixed(1),clipped:(s.clipped_h||0).toFixed(1),full_at:s.full_at_ts?new Date(1e3*s.full_at_ts).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"}):""}):null,r=t.self_consumption,a=r?this._format("energy_plan_review_"+r.code,{actual:Math.round(100*(r.actual_share||0)),predicted:Math.round(100*(r.predicted_share||0))}):null;return e.length||a||i?H`
            <div class="review">
                <div class="rev-h">${this._t("energy_plan_review_title")}</div>
                ${e.map(t=>H`
                    <div class="rev-row">
                        <ha-icon icon="${t.k.icon}"
                                 style="--mdc-icon-size:12px;color:${t.k.color}"></ha-icon>
                        <span class="rev-name">${this._demandName(t.d.label,t.d.demand_id,t.d.kind)}</span>
                        <span class="rev-txt">${t.text}</span>
                    </div>
                `)}
                ${i?H`
                    <div class="rev-row">
                        <ha-icon icon="mdi:battery-arrow-down"
                                 style="--mdc-icon-size:12px;color:#4db6ac"></ha-icon>
                        <span class="rev-name">${this._t("battery")}</span>
                        <span class="rev-txt">${i}</span>
                    </div>`:K}
                ${a?H`
                    <div class="rev-row">
                        <ha-icon icon="mdi:solar-power-variant"
                                 style="--mdc-icon-size:12px;color:#ff9800"></ha-icon>
                        <span class="rev-txt wide">${a}</span>
                    </div>
                `:K}
            </div>
        `:K}_renderArb(t){return t&&t.enabled?H`
            <div class="arb" title="${this._t("energy_plan_arbitrage_tip")}">
                <ha-icon icon="mdi:swap-vertical-bold"
                         style="--mdc-icon-size:13px;color:${t.opportunity?"#8DC892":"var(--secondary-text-color,#8a93a5)"}"></ha-icon>
                <span class="arb-lbl">${this._t("energy_plan_arbitrage")}</span>
                <span class="arb-txt">${t.reason||""}</span>
                ${this._docsLink("arbitrage")}
            </div>
        `:K}_renderIdle(t,e="energy_plan_idle",s="",i=!1,r="",a=[],n=[],o=null){const l=(a||[]).map(t=>this._t("energy_plan_whyc_"+t)).filter(Boolean).join(" · ");return H`
            <ha-card>
                <div class="wrap">
                    <div class="head">
                        <ha-icon icon="mdi:weather-night" style="--mdc-icon-size:16px;color:#8353d1"></ha-icon>
                        <span class="title">${this._t("energy_plan_title")}</span>
                        ${this._viewToggle(i)}
                        ${this._modeChip(t)}
                        ${this._docsLink()}
                    </div>
                    <div class="idle">${this._t(e)}${s}</div>
                    ${l?H`<div class="why" title="${r}">${l}</div>`:r?H`<div class="why" title="${r}">${r}</div>`:K}
                    ${(n||[]).length?H`
                        <div class="notsched">
                            <div class="notsched-h">${this._t("energy_plan_not_scheduled")}</div>
                            ${n.map(t=>H`
                                <div class="notsched-row">
                                    <ha-icon icon="mdi:sleep"
                                             style="--mdc-icon-size:12px;color:var(--secondary-text-color,#8a93a5)"></ha-icon>
                                    <span class="nsname">${this._demandName(t.label,t.id)}</span>
                                    <span class="nswhy">${this._t("energy_plan_why_"+t.why)}</span>
                                </div>
                            `)}
                        </div>
                    `:K}
                    ${this._renderArb(o)}
                    ${this._renderReview()}
                </div>
            </ha-card>
        `}render(){if(!this._hass||!this._config)return K;const t=this._hass.states[this._entity],e=t?.state;if(!t||"unavailable"===e||"unknown"===e)return this.style.display="none",K;this.style.display="";const s=t.attributes||{},i=!0===s.actuation||void 0===s.actuation&&"on"===this._hass.states["switch.sem_energy_plan_actuation"]?.state;if("tomorrow"===(this._view||"today")&&s.tomorrow)return this._renderTomorrow(s.tomorrow);if("pending"===e){const t=this._hass.states["sensor.sem_night_start_time"]?.state,e=t&&/^\d{1,2}:\d{2}$/.test(t)?` (~${t})`:"";return this._renderIdle(i,"energy_plan_pending",e,!!s.tomorrow)}const r=Array.isArray(s.demands)?s.demands:[],a=Array.isArray(s.slots)?s.slots:[],n=Array.isArray(s.blocks)?s.blocks:[];if("idle"===e||!r.length)return this._renderIdle(i,"energy_plan_idle","",!!s.tomorrow,s.why||"",s.why_codes||[],s.not_scheduled||[],s.arbitrage);const o=a.length?Date.parse(a[0].start):NaN,l=a.length?Date.parse(a[a.length-1].end):NaN,c=l-o,d=a.length>0&&Number.isFinite(c)&&c>0,p=this._runs(a,o,c,t=>!!t.cheap).filter(t=>t.v);let _=null;const h=this._hass.states["sensor.sem_night_start_time"]?.state;if(d&&h&&/^\d{1,2}:\d{2}$/.test(h)){const[t,e]=h.split(":").map(Number);for(const s of[0,1]){const i=new Date(o);i.setDate(i.getDate()+s),i.setHours(t,e,0,0);const r=i.getTime();if(r>=o&&r<l){_=(r-o)/c*100;break}}}const u=Date.now(),g=d&&u>=o&&u<l?(u-o)/c*100:null,m=H`
            <div class="band">
                ${p.map(t=>H`
                    <div class="cheap" style="left:${t.left}%;width:${t.width}%"></div>
                `)}
                ${null!==_?H`
                    <div class="nightband" style="left:${_}%;width:${100-_}%"></div>`:K}
                ${null!==g?H`
                    <div class="nowline" style="left:${g}%"></div>`:K}
            </div>
        `;let f=a.filter(t=>0===new Date(t.start).getMinutes());f.length||(f=a);const y=Math.max(1,Math.ceil(f.length/8)),v=f.filter((t,e)=>e%y===0).map(t=>({left:(Date.parse(t.start)-o)/c*100,text:this._hm(t.start)})).filter(t=>t.left<=94),b=function(t){if(!Array.isArray(t))return null;const e=new Set;for(const s of t){if(!Array.isArray(s))continue;const t=Number(s[0]),i=Number(s[1]);if(Number.isInteger(t)&&Number.isInteger(i))for(let s=t;s<=i;s++)e.add(s)}return e}(s.batt_runs),x=this._runs(a,o,c,(t,e)=>{return s=t,i=b?b.has(e):void 0,(s&&s.home_grid_w||0)>1?"grid":void 0===i||i?"batt":"sun";var s,i}),$=new Set(x.map(t=>t.v)),w=!1!==s.has_battery,k=w?s.takeover?this._format("energy_plan_takeover",{time:this._hm(s.takeover)}):this._t("energy_plan_all_night"):"",S=w?s.takeover?H`
                <ha-icon icon="mdi:transmission-tower"
                         style="--mdc-icon-size:12px;color:#488fc2"></ha-icon>
                <span>${this._hm(s.takeover)}</span>
              `:H`
                <ha-icon icon="mdi:home-battery-outline"
                         style="--mdc-icon-size:12px;color:#4db6ac"></ha-icon>
                <span>${this._t("energy_plan_all_night_short")}</span>
              `:K,C=ft(this._hass),z=Number(s.total_cost),M=Number.isFinite(z)?`${this._t("energy_plan_est")} ${z.toFixed(2)} ${C}`:null,D=!1!==s.fits,E={};for(const t of n)(E[t.id]=E[t.id]||[]).push(t);return H`
            <ha-card>
                <div class="wrap">
                    <div class="head">
                        <ha-icon icon="mdi:weather-night" style="--mdc-icon-size:16px;color:#8353d1"></ha-icon>
                        <span class="title">${this._t("energy_plan_title")}</span>
                        ${this._viewToggle(!!s.tomorrow)}
                        ${this._modeChip(i)}
                        ${this._docsLink()}
                        <span class="stamp">${this._hm(s.computed_at)}</span>
                    </div>

                    <div class="verdict">
                        <ha-icon
                            icon="${D?"mdi:check-circle":"mdi:alert-circle-outline"}"
                            style="--mdc-icon-size:15px;color:${D?"#8DC892":"#f06292"}"></ha-icon>
                        <span class="vtext">
                            ${D?this._t("energy_plan_fits"):this._t("energy_plan_yields")}
                        </span>
                        ${M?H`<span class="cost">${M}</span>`:K}
                    </div>

                    <div class="strip ${d?"":"nostrip"}">
                        ${d?H`
                            <div class="lbl axis"></div>
                            <div class="track axis">
                                ${m}
                                ${v.map(t=>H`
                                    <span class="tick ${t.left<4?"first":""}"
                                          style="left:${t.left}%">${t.text}</span>
                                `)}
                                ${a.map(t=>{const e=(Date.parse(t.start)-o)/c*100,s=(Date.parse(t.end)-Date.parse(t.start))/c*100;if(!Number.isFinite(e)||!Number.isFinite(s))return K;const i=null===t.price||void 0===t.price?"—":`${t.price} ${C}`,r=Number.isFinite(t.co2)?` · ${Math.round(1e3*t.co2)} g/kWh`:"",a=`${this._hm(t.start)}–${this._hm(t.end)} · ${i}${r}`+(t.cheap?` · ${this._t("energy_plan_legend_cheap")}`:"");return H`<div class="slotcell" title="${a}"
                                        style="left:${e}%;width:${s}%"></div>`})}
                            </div>
                            <div class="stat axis"></div>
                        `:K}

                        <div class="lbl">
                            <ha-icon icon="${w?"mdi:home-battery":"mdi:home"}"
                                     style="--mdc-icon-size:13px;color:${w?"#4db6ac":"#5BC8D8"}"></ha-icon>
                            <span class="name">${this._t("energy_plan_home")}</span>
                        </div>
                        ${d?H`
                            <div class="track">
                                ${m}
                                ${x.map(t=>H`
                                    <div class="seg ${t.v}"
                                         style="left:${t.left}%;width:${t.width}%"></div>
                                `)}
                            </div>
                        `:K}
                        <div class="stat" title="${k}">${S}</div>

                        ${r.map(t=>{const e=Li[t.kind]||Li.load,r=Wi[t.status]||Wi.yields,a=E[t.id]||[],l=t.label||this._t(e.label),p="fits"===t.status?`${(t.planned_kwh||0).toFixed(1)} kWh`:`${(t.planned_kwh||0).toFixed(1)}/${(t.needed_kwh||0).toFixed(1)} kWh`,_=[l,"comfort"===t.kind?this._t("energy_plan_comfort_tip"):null,a.map(t=>`${this._hm(t.start)}–${this._hm(t.end)} · ${(t.power_w/1e3).toFixed(1)} kW${null!=t.price?` · ${t.price}`:""}`).join("\n")||null,`${(t.planned_kwh||0).toFixed(1)} / ${(t.needed_kwh||0).toFixed(1)} kWh · ${this._t("energy_plan_est")} ${(t.est_cost||0).toFixed(2)} ${C}`,t.note||null].filter(Boolean).join("\n"),h=i?this._liveState(t,n):null,u=t.note||("fits"!==t.status?this._format("energy_plan_yield_reason",{planned:(t.planned_kwh||0).toFixed(1),needed:(t.needed_kwh||0).toFixed(1)}):null);return H`
                                <div class="lbl ${h?"col":""}" title="${_}">
                                    <div class="lname">
                                        <ha-icon icon="${e.icon}" style="--mdc-icon-size:13px;color:${e.color}"></ha-icon>
                                        <span class="name">${l}</span>
                                    </div>
                                    ${this._liveChip(h)}
                                    ${i?this._covChip((s.coverage||{})[t.id]):K}
                                </div>
                                ${d?H`
                                    <div class="track">
                                        ${m}
                                        ${a.map(t=>{const s=(Date.parse(t.start)-o)/c*100,i=(Date.parse(t.end)-Date.parse(t.start))/c*100;return H`
                                                <div class="seg run"
                                                     title="${this._hm(t.start)}–${this._hm(t.end)} · ${Math.round(t.power_w)} W"
                                                     style="left:${s}%;width:${Math.max(i,1.2)}%;background:${e.color}"></div>
                                            `})}
                                    </div>
                                `:K}
                                <div class="stat" title="${_}">
                                    <ha-icon icon="${r.icon}" style="--mdc-icon-size:13px;color:${r.color}"></ha-icon>
                                    <span>${p}</span>
                                </div>
                                ${u?H`
                                    <div class="lbl"></div>
                                    <div class="note">${u}</div>
                                    ${d?H`<div class="stat"></div>`:K}
                                `:K}
                            `})}
                    </div>

                    ${d?H`
                        <div class="legend">
                            ${$.has("sun")?H`<span class="key"><i class="sw sun"></i>${this._t("energy_plan_legend_sun")}</span>`:K}
                            ${$.has("batt")?H`<span class="key"><i class="sw batt"></i>${this._t("energy_plan_legend_battery")}</span>`:K}
                            ${$.has("grid")?H`<span class="key"><i class="sw grid"></i>${this._t("energy_plan_legend_grid")}</span>`:K}
                            <span class="key"><i class="sw cheapkey"></i>${this._t("energy_plan_legend_cheap")}</span>
                        </div>
                    `:H`
                        <div class="warn">
                            <ha-icon icon="mdi:chart-timeline-variant"
                                     style="--mdc-icon-size:13px;color:#ff9800"></ha-icon>
                            <span>${this._t("energy_plan_strip_omitted")}</span>
                        </div>
                    `}

                    ${s.battery_fleet_partial?H`
                        <div class="warn">
                            <ha-icon icon="mdi:alert-outline" style="--mdc-icon-size:13px;color:#ff9800"></ha-icon>
                            <span>${this._t("energy_plan_fleet_partial")}</span>
                        </div>
                    `:K}

                    ${(s.not_scheduled||[]).length?H`
                        <div class="notsched">
                            <div class="notsched-h">${this._t("energy_plan_not_scheduled")}</div>
                            ${s.not_scheduled.map(t=>H`
                                <div class="notsched-row">
                                    <ha-icon icon="mdi:sleep"
                                             style="--mdc-icon-size:12px;color:var(--secondary-text-color,#8a93a5)"></ha-icon>
                                    <span class="nsname">${this._demandName(t.label,t.id)}</span>
                                    <span class="nswhy">${this._t("energy_plan_why_"+t.why)}</span>
                                </div>
                            `)}
                        </div>
                    `:K}

                    ${this._renderArb(s.arbitrage)}

                    ${this._renderReview()}

                    <div class="foot">${this._t(i?"energy_plan_active_note":"energy_plan_shadow_note")}</div>
                </div>
            </ha-card>
        `}static get styles(){return a`
            :host { display: block; }
            ha-card {
                background: var(--card-background-color, #1e232d);
                backdrop-filter: blur(16px) saturate(160%);
                -webkit-backdrop-filter: blur(16px) saturate(160%);
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 14px;
            }
            .wrap { padding: 12px 14px; }
            .head {
                display: flex; align-items: center; gap: 6px;
                margin-bottom: 6px; opacity: 0.9;
            }
            .title {
                font-size: 12px; letter-spacing: 0.04em; text-transform: uppercase;
                color: var(--primary-text-color);
            }
            .chip {
                font-size: 9px; letter-spacing: 0.06em; text-transform: uppercase;
                padding: 1px 6px; border-radius: 8px;
                background: rgba(131,83,209,0.18); color: #b39ddb;
                border: 1px solid rgba(131,83,209,0.35);
            }
            .chip-reactive {
                border-color: rgba(255, 152, 0, 0.6);
                color: #ff9800;
            }
            .notsched {
                margin-top: 6px;
                padding-top: 6px;
                border-top: 1px solid rgba(255, 255, 255, 0.06);
            }
            .notsched-h {
                font-size: 10px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                color: var(--secondary-text-color, #8a93a5);
                margin-bottom: 2px;
            }
            /* (#744) The name column is a NAME now, not an entity slug, so
               it no longer eats the row — but min-width:0 keeps a long one
               from pushing the reason into a two-words-per-line ribbon on a
               phone (the PROD 23:50 card). The reason takes what is left and
               sits right. */
            .notsched-row {
                display: flex;
                align-items: baseline;
                gap: 6px;
                font-size: 11px;
                color: var(--secondary-text-color, #8a93a5);
            }
            .notsched-row .nsname {
                color: var(--primary-text-color, #e1e1e1);
                min-width: 0;
                flex: 0 1 auto;
                overflow-wrap: anywhere;
            }
            .notsched-row .nswhy {
                min-width: 0;
                flex: 1 1 auto;
                text-align: right;
            }
            /* (#755) the record's verdict — same visual weight as the
               not-scheduled list: a footnote, not a headline. */
            .review {
                margin-top: 6px;
                padding-top: 6px;
                border-top: 1px solid rgba(255, 255, 255, 0.06);
            }
            .rev-h {
                font-size: 10px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                color: var(--secondary-text-color, #8a93a5);
                margin-bottom: 2px;
            }
            .rev-row {
                display: flex;
                align-items: baseline;
                gap: 6px;
                font-size: 11px;
                color: var(--secondary-text-color, #8a93a5);
            }
            .rev-row ha-icon { align-self: center; }
            .rev-name {
                color: var(--primary-text-color, #e1e1e1);
                white-space: nowrap;
            }
            .rev-txt { min-width: 0; }
            .chip-active {
                background: rgba(141,200,146,0.18); color: #8DC892;
                border-color: rgba(141,200,146,0.40);
            }
            .docs-link {
                display: inline-flex; align-items: center;
                color: var(--secondary-text-color);
                opacity: 0.6; transition: opacity 0.15s;
            }
            .docs-link:hover { opacity: 1; color: #8353d1; }
            .stamp {
                margin-left: auto; font-size: 11px;
                color: var(--secondary-text-color);
                font-variant-numeric: tabular-nums;
            }
            .verdict {
                display: flex; align-items: center; gap: 6px;
                font-size: 13px; font-weight: 500;
                color: var(--primary-text-color);
                margin-bottom: 10px;
            }
            .cost {
                margin-left: auto; font-size: 12px; font-weight: 400;
                color: var(--secondary-text-color);
                font-variant-numeric: tabular-nums;
            }
            .idle {
                font-size: 13px; color: var(--secondary-text-color);
                padding: 2px 0 2px;
            }
            .strip {
                display: grid;
                /* The label column grows with the card: on a panel-width
                   System tab a fixed 82px truncated "Sim Pool Pump" to
                   "Sim Pool P…" with 700px going spare. */
                grid-template-columns: minmax(82px, 16%) 1fr 92px;
                align-items: center;
                row-gap: 4px; column-gap: 8px;
            }
            /* No timeline (the recorder dropped it) — the label takes the
               track's room so the demand names still read in full. */
            .strip.nostrip { grid-template-columns: 1fr auto; }
            .lbl {
                display: flex; align-items: center; gap: 4px;
                min-width: 0; font-size: 11px;
                color: var(--primary-text-color);
            }
            /* (#638 G4) a row wearing a live chip stacks name over chip. */
            .lbl.col {
                flex-direction: column; align-items: flex-start; gap: 2px;
            }
            .lname {
                display: flex; align-items: center; gap: 4px; min-width: 0;
                max-width: 100%;
            }
            .live {
                font-size: 8.5px; letter-spacing: 0.05em; text-transform: uppercase;
                padding: 0 5px; border-radius: 7px; white-space: nowrap;
            }
            .live.now {
                background: rgba(141,200,146,0.20); color: #8DC892;
                border: 1px solid rgba(141,200,146,0.45);
            }
            .live.wait {
                background: rgba(91,200,216,0.12); color: #5BC8D8;
                border: 1px solid rgba(91,200,216,0.30);
                font-variant-numeric: tabular-nums;
            }
            .live.done {
                background: rgba(255,255,255,0.06); color: var(--secondary-text-color);
                border: 1px solid rgba(255,255,255,0.12);
            }
            .live.react {
                background: rgba(131,83,209,0.16); color: #b39ddb;
                border: 1px solid rgba(131,83,209,0.35);
            }
            /* (#638 G4) invisible hover cells on the axis: per-slot price. */
            .slotcell { position: absolute; top: 0; bottom: 0; }
            .name {
                overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
            }
            .track {
                position: relative; height: 14px; border-radius: 4px;
                background: rgba(255,255,255,0.04);
                overflow: hidden;
            }
            .track.axis {
                height: 13px; background: transparent; overflow: visible;
            }
            .band {
                position: absolute; inset: 0; pointer-events: none;
            }
            .cheap {
                position: absolute; top: 0; bottom: 0;
                background: rgba(141,200,146,0.17);
                box-shadow: inset 1px 0 0 rgba(141,200,146,0.30),
                            inset -1px 0 0 rgba(141,200,146,0.30);
            }
            .seg {
                position: absolute; top: 2px; bottom: 2px; border-radius: 3px;
            }
            .seg.batt { background: #4db6ac; }
            .seg.grid { background: #488fc2; }
            .seg.sun { background: #ff9800; }
            .seg.run { top: 1px; bottom: 1px; }
            .tick {
                position: absolute; top: 0;
                transform: translateX(-50%);
                font-size: 9px; color: var(--secondary-text-color);
                font-variant-numeric: tabular-nums;
                white-space: nowrap;
            }
            /* The first tick sits at 0% — centring it would hang half the
               label off the left edge of the track. Left-align that one. */
            .tick.first {
                transform: none;
                font-size: 9px; color: var(--secondary-text-color);
                font-variant-numeric: tabular-nums;
                white-space: nowrap;
            }
            .stat {
                display: flex; align-items: center; gap: 4px;
                justify-content: flex-end;
                font-size: 11px; color: var(--secondary-text-color);
                font-variant-numeric: tabular-nums;
                white-space: nowrap;
            }
            .note {
                font-size: 10px; opacity: 0.6; line-height: 1.2;
                color: var(--secondary-text-color);
            }
            .legend {
                display: flex; flex-wrap: wrap; gap: 10px;
                margin-top: 9px; font-size: 10px;
                color: var(--secondary-text-color);
            }
            .key { display: inline-flex; align-items: center; gap: 4px; }
            .sw {
                width: 10px; height: 8px; border-radius: 2px; display: inline-block;
            }
            .sw.batt { background: #4db6ac; }
            .sw.grid { background: #488fc2; }
            .sw.sun { background: #ff9800; }
            .sw.cheapkey { background: rgba(141,200,146,0.35); }
            .warn {
                display: flex; align-items: center; gap: 5px;
                margin-top: 8px; font-size: 11px; color: #ffb74d;
            }
            .head { flex-wrap: wrap; row-gap: 4px; }
            .why {
                margin-top: 4px; font-size: 10px; opacity: 0.55;
                color: var(--secondary-text-color);
                overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
            }
            .asks {
                display: flex; flex-wrap: wrap; gap: 6px 10px;
                align-items: center; margin-top: 8px; font-size: 11px;
            }
            .asks-lbl {
                font-weight: 600; color: var(--secondary-text-color, #8a93a5);
            }
            .ask { display: inline-flex; align-items: center; gap: 3px; }
            .prov { opacity: 0.85; }
            .vtoggle {
                display: inline-flex; border: 1px solid rgba(255,255,255,0.14);
                border-radius: 8px; overflow: hidden; margin-left: 2px;
            }
            .vbtn {
                background: none; border: none; cursor: pointer;
                font-size: 10px; padding: 2px 7px;
                color: var(--secondary-text-color, #8a93a5);
            }
            .vbtn-on {
                background: rgba(131,83,209,0.25); color: var(--primary-text-color, #fff);
            }
            .tmw-track { position: relative; height: 18px; margin-top: 8px; }
            .tmw-sun {
                position: absolute; top: 0; height: 100%;
                background: rgba(255,152,0,0.20); border-radius: 3px;
            }
            .tmw-cheap {
                position: absolute; top: 30%; height: 40%;
                background: rgba(141,200,146,0.5); border-radius: 3px;
            }
            .tmw-sun-key { background: rgba(255,152,0,0.45); }
            .nightband {
                position: absolute; top: 0; height: 100%;
                background: rgba(131,83,209,0.10);
            }
            .nowline {
                position: absolute; top: -2px; height: calc(100% + 4px);
                width: 2px; background: #5BC8D8; opacity: 0.8;
            }
            .arb {
                display: flex; align-items: center; gap: 5px;
                margin-top: 8px; font-size: 11px;
                color: var(--secondary-text-color, #8a93a5);
            }
            .arb-lbl { font-weight: 600; white-space: nowrap; }
            .arb-txt {
                overflow: hidden; text-overflow: ellipsis;
                white-space: nowrap; flex: 1; min-width: 0;
            }
            .foot {
                margin-top: 8px; font-size: 10px; opacity: 0.5;
                color: var(--secondary-text-color);
            }
        `}}kt("sem-energy-plan-card",Hi,{type:"sem-energy-plan-card",name:"SEM Energy Plan",description:"The joint plan for the energy day — when each demand runs and where the battery hands over",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-energy-plan-card"}),kt("sem-overnight-plan-card",class extends Hi{});kt("sem-why-card",class extends Lt{static get properties(){return{...super.properties,_records:{state:!0},_chip:{state:!0},_allSettings:{state:!0},_foldOpen:{state:!0},_error:{state:!0}}}constructor(){super(),this._records=null,this._chip="",this._allSettings=!1,this._foldOpen=null,this._error=!1,this._loading=!1,this._stamp=null,this._loadedStamp=void 0,this._failedAt=0,this._boundViewMode=t=>this._applyViewMode(t&&t.detail&&"boolean"==typeof t.detail.all?t.detail.all:Di())}setConfig(t){super.setConfig(t||{}),this._prefix=this._config.entity_prefix||"sensor.sem_"}connectedCallback(){super.connectedCallback(),this._applyViewMode(Di()),window.addEventListener(Mi,this._boundViewMode)}disconnectedCallback(){super.disconnectedCallback(),window.removeEventListener(Mi,this._boundViewMode)}set hass(t){super.hass=t,this._stamp=function(t,e="sensor.sem_"){const s=[t?.[`${e}charging_state`]?.attributes?.per_charger_last_decision,t?.[`${e}battery_status`]?.attributes?.per_battery_last_decision,t?.[`${e}load_management_status`]?.attributes?.per_device_last_decision];let i="",r=0;for(const t of s)for(const e of Object.values(t||{})){r+=1;const t=String(e?.time||"");t>i&&(i=t)}return`${r}|${i}`}(t?.states,this._prefix||"sensor.sem_"),this._maybeLoad()}get hass(){return this._hass}_maybeLoad(t=Date.now()){!this._loading&&this._hass?.callWS&&this._stamp!==this._loadedStamp&&(this._failedAt&&t-this._failedAt<3e4||this._load(this._stamp))}async _load(t=this._stamp){if(this._loading||!this._hass?.callWS)return;this._loading=!0;let e=!1;try{const s=await this._hass.callWS({type:"solar_energy_management/decision_log"});this._records=Array.isArray(s?.records)?s.records:[],this._error=!1,this._loadedStamp=t,this._failedAt=0,e=!0}catch(t){null===this._records&&(this._records=[]),this._error=!0,this._failedAt=Date.now()}finally{this._loading=!1}this.requestUpdate(),e&&this._stamp!==this._loadedStamp&&this._maybeLoad()}_applyViewMode(t){t!==this._allSettings&&(this._allSettings=t,this._foldOpen=null)}_setView(t){Ei(t),this._applyViewMode(t)}_isFoldOpen(){return"boolean"==typeof this._foldOpen?this._foldOpen:this._allSettings}_toggleFold(){this._foldOpen=!this._isFoldOpen()}_setChip(t){this._chip=t}_fill(t,e){return(this._t(t)||"").split("{n}").join(String(e))}_renderRow(t,e){const s=t=>this._t(t),i=li[t.device_kind]||li.load,r=this._hass?.config?.time_zone,a=this._hass?.language||"en",n=this._hass?.config?.currency||"",o=function(t,e,s=""){const i=t||{},r=[],a=t=>`${t.toFixed(2)}${s?` ${s}`:""}/kWh`;return null!==hi(i.solar_w)&&r.push({icon:"mdi:white-balance-sunny",color:"#ff9800",text:ui(i.solar_w)}),null!==hi(i.soc)&&r.push({icon:"mdi:battery-medium",color:"#4db6ac",text:`${Math.round(i.soc)} %`}),null!==hi(i.import_price)&&r.push({text:`${e("why_in_import")} ${a(i.import_price)}`}),null!==hi(i.export_rate)&&r.push({text:`${e("why_in_export")} ${a(i.export_rate)}`}),null!==hi(i.surplus_w)&&r.push({text:`${e("why_in_surplus")} ${ui(i.surplus_w)}`}),null!==hi(i.target_soc)?r.push({text:`${e("why_in_target")} ${Math.round(i.target_soc)} %`}):null!==hi(i.target_kwh)&&i.target_kwh>0&&r.push({text:`${e("why_in_target")} ${i.target_kwh.toFixed(1)} kWh`}),r}(t.inputs,s,n),l=_i(t,s),c=l||t.text;return H`
            <div class="row" data-key=${ci(t)}>
                <div class="time">${function(t,e="en",s=new Date,i){const r=new Date(t);if(Number.isNaN(r.getTime()))return"—";const a={hour:"2-digit",minute:"2-digit",hour12:!1,timeZone:i||void 0};let n,o;try{n=r.toLocaleTimeString(e,a)}catch(t){n=r.toLocaleTimeString([],a)}if(mi(t,s,i))return n;try{o=r.toLocaleDateString(e,{weekday:"short",timeZone:i||void 0})}catch(t){o=""}return o?`${o} ${n}`:n}(t.time,a,new Date,r)}</div>
                <div class="ic" style="background:${i.color}">
                    <ha-icon icon=${i.icon} style="--mdc-icon-size:16px"></ha-icon>
                </div>
                <div class="body">
                    <div class="what">
                        <span class="name">${di(t,s,e[t.device_kind]>1)}</span>
                        <span class="change">${function(t,e){const s=pi(t?.new,e);return t?.old?`${pi(t.old,e)} → ${s}`:s}(t,s)}</span>
                        ${t.observer?H`<span class="tag">${s("why_observer")}</span>`:K}
                    </div>
                    ${c?H`<div class="why" title=${l&&t.text||""}>${c}</div>`:K}
                    ${o.length?H`
                        <div class="in">
                            ${o.map(t=>H`<span>${t.icon?H`<ha-icon icon=${t.icon}
                                style="--mdc-icon-size:13px;color:${t.color}"></ha-icon>`:K}${t.text}</span>`)}
                        </div>`:K}
                </div>
            </div>`}render(){if(!this._hass||!this._config)return K;const t=t=>this._t(t),e=this._records||[],s=function(t,e){const s=new Map;for(const e of t||[]){const t=ci(e);s.has(t)||s.set(t,e)}const i={};for(const t of s.values())i[t.device_kind]=(i[t.device_kind]||0)+1;return[...s.entries()].map(([t,s])=>({key:t,kind:s.device_kind,name:di(s,e,i[s.device_kind]>1)}))}(e,t),i=s.some(t=>t.key===this._chip)?this._chip:"",r={};for(const t of s)r[t.kind]=(r[t.kind]||0)+1;const a=function(t,e){const s=t||[];return e?s.filter(t=>ci(t)===e):s}(e,i),{shown:n,earlier:o}=function(t,e=4){const s=t||[];return{shown:s.slice(0,e),earlier:s.slice(e)}}(a),l=this._isFoldOpen(),c=this._hass?.config?.time_zone;return H`
            <ha-card>
                <div class="wrap">
                    <div class="hd">
                        <span class="title">${t("why_title")}</span>
                        <div class="view-switch" role="group" aria-label=${t("ev_view_label")}>
                            <button class="view-seg ${this._allSettings?"":"on"}" type="button"
                                    aria-pressed=${this._allSettings?"false":"true"}
                                    @click=${()=>this._setView(!1)}>${t("ev_view_everyday")}</button>
                            <button class="view-seg ${this._allSettings?"on":""}" type="button"
                                    aria-pressed=${this._allSettings?"true":"false"}
                                    @click=${()=>this._setView(!0)}>${t("ev_view_all")}</button>
                        </div>
                    </div>
                    ${s.length?H`
                        <div class="chips" role="group">
                            <button type="button" class="chip ${i?"":"on"}"
                                    aria-pressed=${i?"false":"true"}
                                    @click=${()=>this._setChip("")}>${t("why_all")}</button>
                            ${s.map(t=>H`
                                <button type="button" class="chip ${i===t.key?"on":""}"
                                        aria-pressed=${i===t.key?"true":"false"}
                                        @click=${()=>this._setChip(t.key)}>${t.name}</button>`)}
                        </div>`:K}
                    ${this._error?H`<div class="note">${t("why_load_error")}</div>`:K}
                    ${null===this._records||a.length||this._error?K:H`<div class="note">${t("why_empty")}</div>`}
                    <div class="rows">
                        ${n.map(t=>this._renderRow(t,r))}
                    </div>
                    ${o.length?H`
                        <div class="fold ${l?"open":""}">
                            <button class="fold-btn" type="button"
                                    aria-expanded=${l?"true":"false"}
                                    @click=${t=>{t.stopPropagation(),this._toggleFold()}}>
                                <span class="fold-label">${this._fill(function(t,e=new Date,s){return(t||[]).every(t=>mi(t.time,e,s))?"why_earlier_today":"why_earlier"}(o,new Date,c),o.length)}</span>
                                <ha-icon icon=${l?"mdi:chevron-up":"mdi:chevron-down"}
                                         style="--mdc-icon-size:16px"></ha-icon>
                            </button>
                            ${l?H`<div class="fold-body rows">
                                ${o.map(t=>this._renderRow(t,r))}
                            </div>`:K}
                        </div>`:K}
                </div>
            </ha-card>`}static get styles(){return[Ot,a`
            :host { display: block; }
            ha-card { display: block; }
            .wrap { padding: 14px 16px 6px; }
            .hd {
                display: flex; align-items: center; justify-content: space-between;
                gap: 8px; margin-bottom: 10px;
            }
            .title { font-size: 16px; font-weight: 600; }
            .view-switch { display: flex; flex-shrink: 0; }
            .view-seg {
                font: inherit; font-size: 11px; font-weight: 600;
                padding: 3px 10px; min-height: 24px;
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                background: transparent; cursor: pointer;
                color: var(--secondary-text-color, #999);
            }
            .view-seg:first-child { border-radius: 8px 0 0 8px; }
            .view-seg:last-child { border-radius: 0 8px 8px 0; border-left: none; }
            .view-seg.on { background: rgba(141,200,146,0.18); color: #8DC892; }
            .view-seg:focus-visible, .fold-btn:focus-visible, .chip:focus-visible {
                outline: 2px solid #8DC892; outline-offset: 1px;
            }
            .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
            .chip {
                font: inherit; font-size: 12px; padding: 4px 10px; min-height: 28px;
                border-radius: 14px; cursor: pointer; background: transparent;
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                color: var(--secondary-text-color, #999);
            }
            .chip.on { background: rgba(255,255,255,0.12); color: var(--primary-text-color); }
            .row {
                display: grid; grid-template-columns: 46px 28px 1fr; gap: 8px;
                padding: 9px 0; border-top: 1px solid rgba(255,255,255,0.06);
            }
            .time {
                font-size: 12px; padding-top: 4px; font-variant-numeric: tabular-nums;
                color: var(--secondary-text-color, #999);
            }
            .ic {
                width: 26px; height: 26px; border-radius: 50%;
                display: grid; place-items: center; color: #111;
            }
            .body { min-width: 0; }
            .what { line-height: 1.35; }
            .name { font-weight: 600; }
            .change { color: var(--secondary-text-color, #999); margin-left: 4px; }
            .tag {
                display: inline-block; font-size: 10.5px; font-weight: 600;
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius: 6px; padding: 0 5px; margin-left: 6px;
                color: var(--secondary-text-color, #999); vertical-align: 1px;
            }
            .why { font-size: 13px; line-height: 1.4; opacity: 0.9; }
            .in {
                display: flex; flex-wrap: wrap; gap: 4px 10px; margin-top: 3px;
                font-size: 11.5px; color: var(--secondary-text-color, #999);
            }
            .in > span { display: inline-flex; align-items: center; gap: 3px; }
            .note {
                font-size: 13px; padding: 8px 0;
                color: var(--secondary-text-color, #999);
            }
            .fold-btn {
                display: flex; align-items: center; justify-content: space-between;
                width: 100%; min-height: 32px; padding: 4px 0;
                font: inherit; font-size: 11px; font-weight: 600;
                text-transform: uppercase; letter-spacing: 0.05em;
                color: var(--secondary-text-color, #999);
                background: none; border: none; cursor: pointer;
                border-top: 1px solid rgba(255,255,255,0.06);
            }
            .fold-btn:hover { color: var(--primary-text-color, #e0e0e0); }
        `]}},{type:"sem-why-card",name:"SEM Why?",description:"Why SEM changed a device: each command change, its reason and the numbers behind it",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-why-card"});const ji=2,Gi=t=>(...e)=>({_$litDirective$:t,values:e});let Ki=class{constructor(t){}get _$AU(){return this._$AM._$AU}_$AT(t,e,s){this._$Ct=t,this._$AM=e,this._$Ci=s}_$AS(t,e){return this.update(t,e)}update(t,e){return this.render(...e)}};class qi extends Ki{constructor(t){if(super(t),this.it=K,t.type!==ji)throw Error(this.constructor.directiveName+"() can only be used in child bindings")}render(t){if(t===K||null==t)return this._t=void 0,this.it=t;if(t===G)return t;if("string"!=typeof t)throw Error(this.constructor.directiveName+"() called with a non-string value");if(t===this.it)return this._t;this.it=t;const e=[t];return e.raw=e,this._t={_$litType$:this.constructor.resultType,strings:e,values:[]}}}qi.directiveName="unsafeHTML",qi.resultType=1;let Vi=class extends qi{};Vi.directiveName="unsafeSVG",Vi.resultType=2;const Yi=Gi(Vi),Zi={solar:{nameKey:"solar",color:"#ff9800"},grid:{nameKey:"grid",color_import:"#488fc2",color_export:"#8353d1"},battery:{nameKey:"battery",color:"#4db6ac"},home:{nameKey:"home",color:"#5BC8D8"},ev:{nameKey:"ev_charger",color:"#8DC892"},inverter:{nameKey:"inverter",color:"#96CAEE"}};kt("sem-flow-card",class extends Lt{constructor(){super(),this._lastKey="",this._animFrames={},this._currentValues={},this._compact=!1,this._visible=!0,this._deviceConfigSig="",this._devicePositions=[],this._updateTimer=null,this._resizeObserver=null,this._intersectionObserver=null,this._resizeTimeout=null,this._mode="prefix",this._prefix="sensor.sem_",this._entities=null}setConfig(t){if(this._config=t,t.entity_prefix)this._mode="prefix",this._prefix=t.entity_prefix;else{if(!t.entities)throw new Error('sem-flow-card requires either "entities" or "entity_prefix" config');this._mode="entities",this._entities=t.entities}this._showLabels=!1!==t.show_labels,this._showValues=!1!==t.show_values,this._showGlow=!1!==t.show_glow,this._showInverter=!1!==t.show_inverter,this._showEv=!1!==t.show_ev,this._showBattery=!1!==t.show_battery,this.requestUpdate()}set hass(t){this._hass,this._hass=t;const e=t?.language;if(e!==this._lang)return this._lang=e,void this.requestUpdate();const s=bt(t,this._prefix);if(s!==this._lastPVKey)return this._lastPVKey=s,void this.requestUpdate();this._visible&&(clearTimeout(this._updateTimer),this._updateTimer=setTimeout(()=>this._updateFlowsImperative(),100))}get hass(){return this._hass}firstUpdated(){this.isConnected&&this._observe()}connectedCallback(){super.connectedCallback(),this.hasUpdated&&this._observe()}_observe(){this._unobserve(),this._resizeTimeout=null,this._resizeObserver=new ResizeObserver(t=>{this._resizeTimeout&&clearTimeout(this._resizeTimeout),this._resizeTimeout=setTimeout(()=>{for(const e of t){const t=e.contentRect.width<400;t!==this._compact&&(this._compact=t,this._lastKey="",this._deviceConfigSig="",this.requestUpdate())}},100)}),this._resizeObserver.observe(this),this._intersectionObserver=new IntersectionObserver(t=>{this._visible=t[0].isIntersecting;const e=this.renderRoot.querySelector("svg");e&&(e.style.animationPlayState=this._visible?"running":"paused"),this._visible&&this._hass&&this._updateFlowsImperative()},{threshold:.01}),this._intersectionObserver.observe(this),this._onVisibility=()=>{"visible"===document.visibilityState&&this._hass&&(this._visible=!0,this._updateFlowsImperative())},document.addEventListener("visibilitychange",this._onVisibility)}_unobserve(){this._resizeObserver&&(this._resizeObserver.disconnect(),this._resizeObserver=null),this._intersectionObserver&&(this._intersectionObserver.disconnect(),this._intersectionObserver=null),clearTimeout(this._resizeTimeout),this._onVisibility&&(document.removeEventListener("visibilitychange",this._onVisibility),this._onVisibility=null)}disconnectedCallback(){super.disconnectedCallback(),this._unobserve(),clearTimeout(this._updateTimer);for(const t of Object.keys(this._animFrames))cancelAnimationFrame(this._animFrames[t]);this._animFrames={}}updated(){this._setupClickHandlers(),this._updateFlowsImperative()}static get styles(){return a`
            :host { display: block; }
            ha-card {
                overflow: hidden; padding: 0;
                background: var(--ha-card-background, var(--card-background-color, transparent)) !important;
                border-radius: var(--ha-card-border-radius, 12px);
            }
            svg { width: 100%; display: block; }
            .flow-group { transition: opacity 0.8s cubic-bezier(0.4,0,0.2,1); }
            .glow-ring { transition: opacity 1s ease; }
            #soc-arc, #autarky-arc { transition: stroke-dashoffset 1.5s cubic-bezier(0.4,0,0.2,1), stroke 1s ease; }
            text { font-variant-numeric: tabular-nums; }
            @keyframes socPulse { 0%,100%{opacity:1} 50%{opacity:0.6} }
            @keyframes socDrain { 0%,100%{opacity:0.75} 50%{opacity:0.4} }
            .clickable-node { cursor: pointer; pointer-events: bounding-box; }
            .clickable-node:hover { opacity: 0.85; }
            .device-clickable { cursor: pointer; }
            .device-clickable:hover { opacity: 0.85; }
        `}render(){if(!this._config)return K;const t=this._getLayout(),e=t.solar,s=t.inverter,i=t.battery,r=t.grid,a=t.home,n=t.ev,o=(2*Math.PI*t.socR).toFixed(1),l=(2*Math.PI*t.autarkyR).toFixed(1),c=t.font.label,d=t.font.value,p=t.font.sub,_=t.font.homeVal,h="'Segoe UI','Roboto',sans-serif",u=this._getNodeColor("grid_import"),g=this._getNodeColor("grid_export"),m=this._getNodeColor("solar"),f=this._getNodeColor("battery"),y=this._getNodeColor("home"),v=this._getNodeColor("ev"),b=Zi.inverter.color,x=this._hasNode("solar"),$=this._hasNode("battery"),w=this._hasNode("grid"),k=this._hasNode("ev"),S=this._showInverter&&this._hasNode("inverter"),C=xt(this._hass,this._prefix);return H`
            <ha-card>
                <style>${wt}</style>
                ${C.length>=2?H`
                    <div class="pv-strings-row">
                        ${C.map(t=>H`
                            <div class="pv-chip"
                                 title="${t.entityId}"
                                 data-entity="${t.entityId}"
                                 @click=${()=>this._fireMoreInfo(t.entityId)}>
                                <span class="pv-chip-label">${t.name}</span>
                                <span class="pv-chip-value">${$t(t.watts)}</span>
                            </div>
                        `)}
                    </div>
                `:K}
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="${t.vb}" style="background:transparent">
                    <defs>
                        <radialGradient id="bgGrad" cx="50%" cy="45%" r="60%">
                            <stop offset="0%" style="stop-color:var(--primary-text-color,#c8dcf0);stop-opacity:0.04"/>
                            <stop offset="100%" style="stop-color:transparent;stop-opacity:0"/>
                        </radialGradient>
                        <pattern id="dotGrid" width="50" height="50" patternUnits="userSpaceOnUse">
                            <circle cx="25" cy="25" r="0.7" fill="var(--secondary-text-color,#808080)" opacity="0.12"/>
                        </pattern>
                        ${this._svgRaw(this._glowFilter("glowSolar",m,8))}
                        ${this._svgRaw(this._glowFilter("glowBattery",f,8))}
                        ${this._svgRaw(this._glowFilter("glowGridImport",u,8))}
                        ${this._svgRaw(this._glowFilter("glowGridExport",g,8))}
                        ${this._svgRaw(this._glowFilter("glowHome",y,10))}
                        ${this._svgRaw(this._glowFilter("glowEV",v,8))}
                        ${this._svgRaw(this._glowFilter("glowInverter",b,6))}
                    </defs>

                    <rect width="100%" height="100%" fill="url(#bgGrad)"/>
                    <rect width="100%" height="90%"  fill="url(#dotGrid)"/>

                    ${this._svgRaw(x?this._track(t.paths.solar,m):"")}
                    ${this._svgRaw(x||S?this._track(t.paths.home,y):"")}
                    ${this._svgRaw($?this._track(t.paths.battery,f):"")}
                    ${this._svgRaw(w?`<path id="track-grid" d="${t.paths.grid}" fill="none" stroke="${u}" stroke-width="1.5" stroke-dasharray="4,6" opacity="0.18"/>`:"")}
                    ${this._svgRaw(k?this._track(t.paths.ev,v):"")}

                    ${this._svgRaw(x?`<g id="flow-solar" class="flow-group" style="opacity:0" data-path-d="${t.paths.solar}" data-color="${m}" data-count="2"></g>`:"")}
                    ${this._svgRaw($?`<g id="flow-battery" class="flow-group" style="opacity:0" data-path-d="${t.paths.battery}" data-color="${f}" data-count="3"></g>`:"")}
                    ${this._svgRaw(w?`<g id="flow-grid" class="flow-group" style="opacity:0" data-path-d="${t.paths.grid}" data-color="${u}" data-count="3"></g>`:"")}
                    ${this._svgRaw(x||S?`<g id="flow-home" class="flow-group" style="opacity:0" data-path-d="${t.paths.home}" data-color="${y}" data-count="2"></g>`:"")}
                    ${this._svgRaw(k?`<g id="flow-ev" class="flow-group" style="opacity:0" data-path-d="${t.paths.ev}" data-color="${v}" data-count="3"></g>`:"")}

                    ${this._svgRaw(x?`\n                    <g id="node-solar" filter="url(#glowSolar)">\n                        ${this._glowRing(e,m)}\n                        <circle cx="${e.cx}" cy="${e.cy}" r="${e.r}" fill="${this._hexToRgba(m,.07)}" stroke="${m}" stroke-width="1.8"/>\n                        <g transform="translate(${e.cx},${e.cy-8})" stroke="${m}" fill="none" opacity="0.75">\n                            <rect x="-16" y="-12" width="32" height="24" rx="3" stroke-width="1.8"/>\n                            <line x1="-16" y1="0" x2="16" y2="0" stroke-width="1.2"/>\n                            <line x1="-5" y1="-12" x2="-5" y2="12" stroke-width="1.2"/>\n                            <line x1="5" y1="-12" x2="5" y2="12" stroke-width="1.2"/>\n                            <line x1="0" y1="12" x2="0" y2="17" stroke-width="1.5"/>\n                            <line x1="-7" y1="17" x2="7" y2="17" stroke-width="1.5"/>\n                        </g>\n                    </g>\n                    <text x="${e.cx}" y="${e.cy+e.r+18}" text-anchor="middle" font-family="${h}" font-size="${c}" font-weight="600" fill="${m}">${this._escSvg(this._getNodeName("solar"))}</text>\n                    <text id="val-solar" x="${e.cx}" y="${e.cy+e.r+18+.9*d}" text-anchor="middle" font-family="${h}" font-size="${d}" font-weight="700" fill="${m}">— W</text>\n                    <text id="val-today-solar" x="${e.cx}" y="${e.cy+e.r+18+.9*d+p+4}" text-anchor="middle" font-family="${h}" font-size="${p}" fill="${m}" opacity="0.7"> </text>\n                    `:"")}

                    ${this._svgRaw(S?`\n                    <g id="node-inverter" filter="url(#glowInverter)">\n                        <circle cx="${s.cx}" cy="${s.cy}" r="${s.r}" fill="${this._hexToRgba(b,.07)}" stroke="${b}" stroke-width="1"/>\n                        <path d="M${s.cx-10},${s.cy} Q${s.cx-4},${s.cy-8} ${s.cx},${s.cy} Q${s.cx+4},${s.cy+8} ${s.cx+10},${s.cy}" fill="none" stroke="${b}" stroke-width="1.8" opacity="0.7"/>\n                    </g>\n                    <text id="val-inverter-status" x="${s.cx}" y="${s.cy+s.r+14}" text-anchor="middle" font-family="${h}" font-size="${this._compact?11:10}" fill="var(--secondary-text-color,#5a7a9a)" opacity="0.7"> </text>\n                    `:"")}

                    ${this._svgRaw($?`\n                    <g id="node-battery" filter="url(#glowBattery)">\n                        ${this._glowRing(i,f)}\n                        <circle cx="${i.cx}" cy="${i.cy}" r="${i.r}" fill="${this._hexToRgba(f,.07)}" stroke="${f}" stroke-width="1.8"/>\n                        <circle cx="${i.cx}" cy="${i.cy}" r="${t.socR}" fill="none" stroke="${this._hexToRgba(f,.1)}" stroke-width="5"/>\n                        <circle id="soc-arc" cx="${i.cx}" cy="${i.cy}" r="${t.socR}" fill="none" stroke="${f}" stroke-width="5"\n                                stroke-dasharray="${o}" stroke-dashoffset="${o}"\n                                transform="rotate(-90 ${i.cx} ${i.cy})" stroke-linecap="round" opacity="0.75"/>\n                        <g transform="translate(${i.cx},${i.cy}) scale(0.8)" stroke="${f}" fill="none" opacity="0.7">\n                            <rect x="-8" y="-13" width="16" height="26" rx="3" stroke-width="1.8"/>\n                            <rect x="-3" y="-16" width="6" height="4" rx="1.5" fill="${f}" opacity="0.5" stroke="none"/>\n                        </g>\n                    </g>\n                    <text x="${i.cx}" y="${i.cy+i.r+18}" text-anchor="middle" font-family="${h}" font-size="${c}" font-weight="600" fill="${f}">${this._escSvg(this._getNodeName("battery"))}</text>\n                    <text id="val-battery-soc" x="${i.cx}" y="${i.cy+i.r+18+.9*d}" text-anchor="middle" font-family="${h}" font-size="${d}" font-weight="700" fill="${f}">—%</text>\n                    <text id="val-battery-power" x="${i.cx}" y="${i.cy+i.r+18+.9*d+c}" text-anchor="middle" font-family="${h}" font-size="${c}" font-weight="500" fill="${f}" opacity="0.7">— W</text>\n                    <text id="label-battery-state" x="${i.cx}" y="${i.cy+i.r+18+.9*d+2*c}" text-anchor="middle" font-family="${h}" font-size="${p}" fill="${f}" opacity="0.7"></text>\n                    <text id="val-today-battery" x="${i.cx}" y="${i.cy+i.r+18+.9*d+2*c+p+4}" text-anchor="middle" font-family="${h}" font-size="${p}" fill="${f}" opacity="0.65"> </text>\n                    `:"")}

                    ${this._svgRaw(w?`\n                    <g id="node-grid" filter="url(#glowGridImport)">\n                        ${this._glowRing(r,u)}\n                        <circle id="grid-circle" cx="${r.cx}" cy="${r.cy}" r="${r.r}" fill="${this._hexToRgba(u,.07)}" stroke="${u}" stroke-width="1.8"/>\n                        <g id="grid-icon" transform="translate(${r.cx},${r.cy})" stroke="${u}" fill="none" opacity="0.7" stroke-width="1.8" stroke-linecap="round">\n                            <line x1="0" y1="-16" x2="0" y2="14"/>\n                            <line x1="-10" y1="-8" x2="10" y2="-8"/>\n                            <line x1="-7" y1="-1" x2="7" y2="-1"/>\n                            <line x1="-10" y1="-8" x2="-5" y2="14"/>\n                            <line x1="10" y1="-8" x2="5" y2="14"/>\n                        </g>\n                    </g>\n                    <text x="${r.cx}" y="${r.cy+r.r+18}" text-anchor="middle" font-family="${h}" font-size="${c}" font-weight="600" fill="${u}">${this._escSvg(this._getNodeName("grid"))}</text>\n                    <text id="val-grid" x="${r.cx}" y="${r.cy+r.r+18+.9*d}" text-anchor="middle" font-family="${h}" font-size="${d}" font-weight="700" fill="${u}">— W</text>\n                    <text id="label-grid" x="${r.cx}" y="${r.cy+r.r+18+.9*d+c}" text-anchor="middle" font-family="${h}" font-size="${p}" font-weight="500" fill="${u}" opacity="0.7">GRID</text>\n                    <text id="val-today-grid" x="${r.cx}" y="${r.cy+r.r+18+.9*d+c+p+4}" text-anchor="middle" font-family="${h}" font-size="${p}" fill="${u}" opacity="0.65"> </text>\n                    `:"")}

                    <g id="node-home" filter="url(#glowHome)">
                        ${this._svgRaw(this._glowRing(a,y,1.4))}
                        <circle cx="${a.cx}" cy="${a.cy}" r="${a.r}" fill="${this._hexToRgba(y,.06)}" stroke="${y}" stroke-width="2"/>
                        <circle cx="${a.cx}" cy="${a.cy}" r="${t.autarkyR}" fill="none" stroke="${this._hexToRgba(y,.08)}" stroke-width="4"/>
                        <circle id="autarky-arc" cx="${a.cx}" cy="${a.cy}" r="${t.autarkyR}" fill="none" stroke="#4CAF50" stroke-width="4"
                                stroke-dasharray="${l}" stroke-dashoffset="${l}"
                                transform="rotate(-90 ${a.cx} ${a.cy})" stroke-linecap="round" opacity="0"/>
                        <g transform="translate(${a.cx},${a.cy-5})" stroke="${y}" fill="none" opacity="0.6" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M-20,2 L0,-14 L20,2"/>
                            <rect x="-14" y="2" width="28" height="20" rx="2"/>
                            <rect x="-4" y="10" width="8" height="12"/>
                        </g>
                    </g>
                    <text x="${a.cx}" y="${a.cy+a.r+18}" text-anchor="middle" font-family="${h}" font-size="${c+1}" font-weight="600" fill="${y}">${this._escSvg(this._getNodeName("home"))}</text>
                    <text id="val-home" x="${a.cx}" y="${a.cy+a.r+18+.9*_}" text-anchor="middle" font-family="${h}" font-size="${_}" font-weight="700" fill="${y}">— W</text>
                    <text id="val-autarky" x="${a.cx}" y="${a.cy+a.r+18+.9*_+p+4}" text-anchor="middle" font-family="${h}" font-size="${p}" fill="${y}" opacity="0.7">\u00A0</text>
                    <text id="val-today-home" x="${a.cx}" y="${a.cy+a.r+18+.9*_+2*(p+4)}" text-anchor="middle" font-family="${h}" font-size="${p}" fill="${y}" opacity="0.65">\u00A0</text>

                    ${this._svgRaw(k?`\n                    <g id="node-ev" filter="url(#glowEV)">\n                        ${this._glowRing(n,v)}\n                        <circle cx="${n.cx}" cy="${n.cy}" r="${n.r}" fill="${this._hexToRgba(v,.07)}" stroke="${v}" stroke-width="1.8"/>\n                        <g transform="translate(${n.cx},${n.cy})" stroke="${v}" fill="none" opacity="0.7" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">\n                            <rect x="-8" y="-13" width="16" height="22" rx="3"/>\n                            <rect x="-5" y="-9" width="10" height="8" rx="1.5"/>\n                            <path d="M-1,-1 L0,3 L1,-1"/>\n                            <line x1="0" y1="9" x2="0" y2="13"/>\n                            <circle cx="0" cy="15" r="1.5" fill="${v}" opacity="0.4" stroke="none"/>\n                        </g>\n                    </g>\n                    <text x="${n.cx}" y="${n.cy+n.r+18}" text-anchor="middle" font-family="${h}" font-size="${c}" font-weight="600" fill="${v}">${this._escSvg(this._getNodeName("ev"))}</text>\n                    <text id="val-ev" x="${n.cx}" y="${n.cy+n.r+18+.9*d}" text-anchor="middle" font-family="${h}" font-size="${d}" font-weight="700" fill="${v}">— W</text>\n                    <text id="val-today-ev" x="${n.cx}" y="${n.cy+n.r+18+.9*d+p+4}" text-anchor="middle" font-family="${h}" font-size="${p}" fill="${v}" opacity="0.65"> </text>\n                    <text id="val-ev-subtitle" x="${n.cx}" y="${n.cy+n.r+18+.9*d+2*(p+4)}" text-anchor="middle" font-family="${h}" font-size="${p-1}" fill="${v}" opacity="0.6"></text>\n                    `:"")}

                    <g id="device-labels"></g>

                    <text x="${this._compact?470:960}" y="${this._compact?1050:770}" text-anchor="end"
                          font-family="${h}" font-size="10" font-weight="300" letter-spacing="2"
                          fill="var(--secondary-text-color,#808080)" opacity="0.15">SEM</text>
                </svg>
            </ha-card>
        `}_svgRaw(t){return t?Yi(t):K}_escSvg(t){return t?String(t).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"):""}_updateFlowsImperative(){if(!this._hass)return;const t=this._powerSnapshot(),e=t=>{const e=parseFloat(t);return isNaN(e)?0:e},s=t=>this._getState(t)??0;let i,r=t?e(t.solar_w):this._getState("solar_power")??0;this._entities?.solar?.reverse&&(r=-r);const a="entities"===this._mode&&(this._entities?.battery?.charge||this._entities?.battery?.discharge);if(a)i=s("battery_charge_power")-s("battery_discharge_power");else if(t)i=e(t.battery_w);else{let t=s("battery_power");i=this._entities?.battery?.reverse?-t:t}let n,o;const l="entities"===this._mode&&this._entities?.grid?.entity;if(l){const t=s("grid_power"),e=this._entities.grid.reverse;n=Math.max(0,e?-t:t),o=Math.max(0,e?t:-t)}else t?(n=e(t.grid_import_w),o=e(t.grid_export_w)):(n=s("grid_import_power"),o=s("grid_export_power"));let c=t?e(t.ev_w):this._getState("ev_power")??0;this._entities?.ev?.invert&&(c=-c);const d=t?null==t.battery_soc?null:e(t.battery_soc):this._getState("battery_soc"),p=this._getState("autarky_rate"),_=this._isOut("solar_power"),h=l?this._isOut("grid_power"):this._pairOut("grid_import_power","grid_export_power"),u=a?this._pairOut("battery_charge_power","battery_discharge_power"):this._isOut("battery_power"),g=this._isOut("ev_power"),m=Math.max(0,i),f=Math.max(0,-i);let y;if(t&&null!==t.home_w&&void 0!==t.home_w)y=e(t.home_w);else{const t=this._getEntityId("home_consumption_power");t&&this._hass?.states[t]?(y=this._getState("home_consumption_power"),null!=y&&this._entities?.home?.invert&&(y=-y)):y=_||h?null:Math.max(0,r+n+f-o-m-c)}const v=this._getStateStr("daily_solar_energy"),b=this._getStateStr("daily_ev_energy"),x=this._getStateStr("daily_grid_import_energy"),$=this._getStateStr("daily_grid_export_energy"),w=this._getStateStr("daily_battery_energy"),k=this._getStateStr("daily_home_energy"),S={solar:r,battery:i,gridImport:n,gridExport:o,home:y,ev:c,soc:d,autarky:p,dailySolar:v,dailyEv:b,dailyGridImport:x,dailyGridExport:$,dailyBattery:w,dailyHome:k,solarOut:_,gridOut:h,battOut:u,evOut:g},C=JSON.stringify(S);if(this._lastKey===C)return;this._lastKey=C,this._animateValue("val-solar",_?null:r);const z=i>10?"▼ ":i<-10?"▲ ":"";this._animateValue("val-battery-power",u?null:Math.abs(i),800,t=>z+ut(t));const M=n>o,D=M?"↓ ":o>10?"↑ ":"";this._animateValue("val-grid",h?null:M?n:o,800,t=>D+ut(t)),this._animateValue("val-home",y),this._animateValue("val-ev",g?null:c);const E=this._getState("ev_charger_count");this._setText("val-ev-subtitle",E>1?`(${E} ${this._t("chargers")})`:""),this._animateValue("val-battery-soc",d,800,t=>`${Tt(t,0)}%`);const N=this._getEntityId("autarky_rate");N&&this._animateValue("val-autarky",p,800,t=>`⚡ ${Tt(t,0)}% ${this._t("self_word")}`),this._setText("val-inverter-status",this._getStateStr("charging_state"));const F=this._t("today");this._setText("val-today-solar",v?`${F} ${v} kWh`:""),this._setText("val-today-ev",b?`${F} ${b} kWh`:""),this._setText("val-today-battery",w?`${F} ${w} kWh`:""),this._setText("val-today-home",k?`${F} ${k} kWh`:"");const A=[];if(x&&A.push(`↓${x}`),$&&A.push(`↑${$}`),x&&$){const t=(parseFloat(x)-parseFloat($)).toFixed(1);A.push(`Net ${t>0?"+":""}${t}`)}this._setText("val-today-grid",A.length?A.join(" ")+" kWh":"");const T=this._getLayout(),I=this.renderRoot.getElementById("soc-arc");if(I){const t=2*Math.PI*T.socR;I.style.strokeDashoffset=(t*(1-(d??0)/100)).toFixed(1),I.style.animation=m>10?"socPulse 2s ease-in-out infinite":f>10?"socDrain 2.5s ease-in-out infinite":"none"}const R=this.renderRoot.getElementById("autarky-arc");if(R&&N&&p>0){const t=2*Math.PI*T.autarkyR;R.style.strokeDashoffset=(t*(1-p/100)).toFixed(1),R.style.stroke=this._autarkyColor(p),R.style.opacity="0.75"}else R&&(R.style.opacity="0");const B=M?this._getNodeColor("grid_import"):o>10?this._getNodeColor("grid_export"):this._getNodeColor("grid_import");this._updateGridColor(B,M);const O=this.renderRoot.getElementById("label-grid");O&&(O.textContent=M?this._t("importing"):o>10?this._t("exporting"):this._t("grid"));const L=m>10?"#f06292":f>10?"#4db6ac":this._getNodeColor("battery"),P=this.renderRoot.getElementById("label-battery-state");P&&(P.textContent=m>10?this._t("charging"):f>10?this._t("discharging"):"");for(const t of["val-battery-soc","val-battery-power","label-battery-state","val-today-battery"]){const e=this.renderRoot.getElementById(t);e&&e.setAttribute("fill",L)}const U=this.renderRoot.getElementById("soc-arc");U&&(m>10||f>10)&&(U.style.stroke=L),this._updateFlow("flow-solar",r>10,!1,mt(r)),this._updateFlow("flow-battery",Math.abs(i)>10,i<0,mt(i),L),this._updateFlow("flow-grid",n>10||o>10,M,mt(n||o),B),this._updateFlow("flow-home",y>10,!1,mt(y??0)),this._updateFlow("flow-ev",c>10,!1,mt(c)),this._setGlowIntensity("node-solar",r,1e4),this._setGlowIntensity("node-battery",Math.abs(i),5e3),this._setGlowIntensity("node-grid",Math.max(n,o),1e4),this._setGlowIntensity("node-home",y??0,8e3),this._setGlowIntensity("node-ev",c,11e3),this._updateDeviceLabels()}_updateFlow(t,e,s,i,r){const a=this.renderRoot.getElementById(t);if(!a)return;if(a.style.opacity=e?"1":"0",!e)return void(a.dataset.sig="");const n=r||a.dataset.color;r&&(a.dataset.color=r);const o=a.dataset.pathD,l=parseInt(a.dataset.count,10)||2,c=`${s?"r":"f"}:${i.toFixed(1)}:${n}`;a.dataset.sig!==c&&(a.dataset.sig=c,a.innerHTML=this._flowEffects(o,n,l,i,s))}_flowEffects(t,e,s,i,r){const a=i.toFixed(1),n=r?' keyPoints="1;0" keyTimes="0;1"':"";let o=`<path d="${t}" fill="none" stroke="${e}" stroke-width="3"\n                     stroke-dasharray="12,20" opacity="0.5" stroke-linecap="round">\n                     <animate attributeName="stroke-dashoffset" from="0" to="${r?"32":"-32"}"\n                              dur="${a}s" repeatCount="indefinite"/>\n                   </path>`;for(let r=0;r<s;r++){const l=r/s*i;o+=`\n                <circle r="5" fill="${e}" opacity="0.12">\n                    <animateMotion path="${t}" dur="${a}s" repeatCount="indefinite" calcMode="paced"${n} begin="-${l.toFixed(2)}s"/>\n                </circle>\n                <circle r="2.5" fill="${e}" opacity="0.9">\n                    <animateMotion path="${t}" dur="${a}s" repeatCount="indefinite" calcMode="paced"${n} begin="-${l.toFixed(2)}s"/>\n                </circle>`}return o}_updateGridColor(t,e){const s=this.renderRoot.getElementById("node-grid");s&&s.setAttribute("filter",`url(#glowGrid${e?"Import":"Export"})`);const i=this.renderRoot.getElementById("grid-circle");i&&(i.setAttribute("stroke",t),i.setAttribute("fill",this._hexToRgba(t,.07)));const r=this.renderRoot.querySelector("#node-grid .glow-ring");r&&r.setAttribute("stroke",t);const a=this.renderRoot.getElementById("grid-icon");a&&a.setAttribute("stroke",t);for(const e of["val-grid","label-grid","val-today-grid"]){const s=this.renderRoot.getElementById(e);s&&s.setAttribute("fill",t)}const n=this.renderRoot.getElementById("track-grid");n&&n.setAttribute("stroke",t)}_updateDeviceLabels(){const t=this.renderRoot.getElementById("device-labels");if(!t)return;const e=this._getDeviceList(),s=e.map(([t,e],s)=>`${e.power_entity}:${e.name}:${e.color||_t[s%_t.length]}:${e.icon_override||""}:${e.daily_energy_entity||""}`).join("|");this._deviceConfigSig!==s&&(this._deviceConfigSig=s,this._buildDeviceDOM(t,e)),this._updateDeviceValues(e)}_getDeviceList(){let t=[];if("entities"===this._mode&&this._entities?.individual)t=this._entities.individual.map((t,e)=>[t.entity||`device_${e}`,{name:t.name||t.entity?.split(".").pop()||`Device ${e+1}`,power_entity:t.entity,device_type:t.device_type||"appliance",is_on:!1,current_power:0,color:t.color,icon_override:t.icon,daily_energy_entity:t.daily_energy}]);else if("prefix"===this._mode){const e=this._hass.states[`${this._prefix}controllable_devices_count`];e?.attributes?.devices&&(t=Object.entries(e.attributes.devices).filter(([,t])=>t.power_entity||t.current_power>0).sort((t,e)=>(t[1].priority||5)-(e[1].priority||5)))}return t.slice(0,6)}_buildDeviceDOM(t,e){if(!e.length)return t.innerHTML="",void(this._devicePositions=[]);const s="'Segoe UI','Roboto',sans-serif",i=this._getLayout(),r=i.home,a=this._compact,n=a?26:24,o=a?2:Math.min(e.length,3),l=a?30:60,c=((a?500:1e3)-2*l)/o,d=i.deviceY,p=a?18:20;let _="";this._devicePositions=[],e.forEach(([t,e],i)=>{let h=e.name||t;h.length>p&&(h=h.substring(0,p-1)+"…");const u=e.color||_t[i%_t.length],g=this._deviceIcon(e.device_type,e.name||t),m=i%o,f=Math.floor(i/o),y=l+m*c+c/2,v=d+f*(a?100:90);this._devicePositions.push({cx:y,cy:v,nodeR:n,color:u}),_+=`<path id="dev-conn-${i}" d="M${r.cx},${r.cy+r.r} C${r.cx},${r.cy+r.r+30} ${y},${v-40} ${y},${v-n}" fill="none" stroke="${u}" stroke-width="1.2" stroke-dasharray="3,5" opacity="0.1"/>`,_+=`<g id="dev-flow-${i}"></g>`;const b=e.power_entity?` data-entity="${e.power_entity}"`:"";_+=`<g id="dev-group-${i}" class="device-clickable"${b} data-idx="${i}">`,_+=`<circle id="dev-circle-${i}" cx="${y}" cy="${v}" r="${n}" fill="rgba(128,128,128,0.03)" stroke="${u}" stroke-width="1.2" opacity="0.4"/>`,_+=`<g transform="translate(${y},${v})" stroke="${u}" fill="none" opacity="0.35" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">${g}</g>`,_+=`<text x="${y}" y="${v+n+14}" text-anchor="middle" font-family="${s}" font-size="11" font-weight="500" fill="${u}" opacity="0.8">${this._escSvg(h)}</text>`,_+=`<text id="dev-val-${i}" x="${y}" y="${v+n+14+11+2}" text-anchor="middle" font-family="${s}" font-size="11" font-weight="600" fill="${u}" opacity="0.7">0 W</text>`,_+=`<text id="dev-daily-${i}" x="${y}" y="${v+n+14+26}" text-anchor="middle" font-family="${s}" font-size="11" fill="${u}" opacity="0.65"></text>`,_+="</g>"}),t.innerHTML=_,t.querySelectorAll(".device-clickable[data-entity]").forEach(t=>{const e=parseInt(t.dataset.idx);this._setupNodeActions(t,`device_${e}`,t.dataset.entity)}),e.forEach((t,e)=>{delete this._currentValues[`dev-val-${e}`]})}_updateDeviceValues(t){const e=this._getLayout().home;t.forEach(([t,s],i)=>{const r=s.power_entity?this._hass.states[s.power_entity]:null,a=r?At(r):s.current_power||0,n=a>5,o=s.color||_t[i%_t.length],l=this._devicePositions[i];if(!l)return;if(this._animateValue(`dev-val-${i}`,a),s.daily_energy_entity){const t=this._hass.states[s.daily_energy_entity];this._setText(`dev-daily-${i}`,t?`${this._t("today")} ${Ft(t)?Nt:t.state} kWh`:"")}const c=this.renderRoot.getElementById(`dev-conn-${i}`);c&&c.setAttribute("opacity",n?"0.3":"0.1");const d=this.renderRoot.getElementById(`dev-circle-${i}`);d&&(d.setAttribute("fill",`rgba(128,128,128,${n?.08:.03})`),d.setAttribute("opacity",n?"1":"0.4"));const p=this.renderRoot.getElementById(`dev-val-${i}`);p&&p.setAttribute("opacity",n?"1":"0.5");const _=this.renderRoot.getElementById(`dev-group-${i}`);if(_){const t=_.querySelector("g[transform]");t&&t.setAttribute("opacity",n?"0.7":"0.35")}const h=this.renderRoot.getElementById(`dev-flow-${i}`);if(h)if(a>5){const t=mt(a).toFixed(1);if(h.dataset.sig!==t){h.dataset.sig=t;const s=`M${e.cx},${e.cy+e.r} C${e.cx},${e.cy+e.r+30} ${l.cx},${l.cy-40} ${l.cx},${l.cy-l.nodeR}`;h.innerHTML=`\n                            <path d="${s}" fill="none" stroke="${o}" stroke-width="2" stroke-dasharray="8,16" opacity="0.4" stroke-linecap="round">\n                                <animate attributeName="stroke-dashoffset" from="0" to="-24" dur="${t}s" repeatCount="indefinite"/>\n                            </path>\n                            <circle r="2" fill="${o}" opacity="0.8">\n                                <animateMotion path="${s}" dur="${t}s" repeatCount="indefinite" calcMode="paced" begin="-${(.3*i).toFixed(1)}s"/>\n                            </circle>`}}else""!==h.dataset.sig&&(h.dataset.sig="",h.innerHTML="")})}_setupClickHandlers(){const t={"node-solar":"solar_power","val-solar":"solar_power","val-today-solar":"daily_solar_energy","node-battery":"battery_soc","val-battery-soc":"battery_soc","val-battery-power":"battery_power","label-battery-state":"battery_power","val-today-battery":"daily_battery_energy","node-grid":"grid_import_power","val-grid":"grid_import_power","label-grid":"grid_import_power","val-today-grid":"daily_grid_import_energy","node-home":"home_consumption_power","val-home":"home_consumption_power","val-autarky":"autarky_rate","val-today-home":"daily_home_energy","node-ev":"ev_power","val-ev":"ev_power","val-today-ev":"daily_ev_energy","val-inverter-status":"charging_state"};for(const[e,s]of Object.entries(t)){const t=this._getEntityId(s);if(!t)continue;const i=this.renderRoot.getElementById(e);i&&(i.setAttribute("data-entity",t),i.style.cursor="pointer")}const e=this.renderRoot.querySelector("svg");e&&!e._semClickBound&&(e._semClickBound=!0,e.addEventListener("click",t=>{let s=t.target;for(let t=0;t<5&&s&&s!==e;t++){const t=s.getAttribute?.("data-entity");if(t)return void this._fireMoreInfo(t);s=s.parentElement}}));const s=[{ids:["node-solar"],node:"solar",key:"solar_power"},{ids:["node-battery"],node:"battery",key:"battery_soc"},{ids:["node-grid"],node:"grid",key:"grid_import_power"},{ids:["node-home"],node:"home",key:"home_consumption_power"},{ids:["node-ev"],node:"ev",key:"ev_power"}];for(const{ids:t,node:e,key:i}of s){const s=this._getEntityId(i);if(s)for(const i of t){const t=this.renderRoot.getElementById(i);t&&!t._semActionsBound&&(t._semActionsBound=!0,t.classList.add("clickable-node"),this._setupNodeActions(t,e,s))}}}_setupNodeActions(t,e,s){let i=null,r=!1,a=0,n=null;t.style.cursor="pointer",t.addEventListener("pointerdown",()=>{r=!1,i=setTimeout(()=>{r=!0;const t=this._getActionConfig(e,"hold_action");"none"!==t.action&&this._handleAction(t,s)},500)}),t.addEventListener("pointerup",()=>clearTimeout(i)),t.addEventListener("pointercancel",()=>{clearTimeout(i),r=!1}),t.addEventListener("click",()=>{if(r)return void(r=!1);const t=this._getActionConfig(e,"double_tap_action");if(!t||"none"===t.action)return void this._handleAction(this._getActionConfig(e,"tap_action"),s);const i=Date.now();i-a<300?(clearTimeout(n),a=0,this._handleAction(t,s)):(a=i,n=setTimeout(()=>{a=0,this._handleAction(this._getActionConfig(e,"tap_action"),s)},300))})}_getActionConfig(t,e){const s=this._entities;if(!s)return{action:"tap_action"===e?"more-info":"none"};let i;if(t.startsWith("device_")){const e=parseInt(t.split("_")[1]);i=s.individual?.[e]}else{i={solar:s.solar,battery:s.battery,grid:s.grid,home:s.home,ev:s.ev||s.individual?.[0]}[t]}const r=i?.[e];return r?"string"==typeof r?{action:r}:r:{action:"tap_action"===e?"more-info":"none"}}_handleAction(t,e){switch(t||(t={action:"more-info"}),t.action){case"more-info":this._fireMoreInfo(t.entity||e);break;case"toggle":this._hass&&this._hass.callService("homeassistant","toggle",{entity_id:t.entity||e});break;case"navigate":t.navigation_path&&(window.history.pushState(null,"",t.navigation_path),window.dispatchEvent(new CustomEvent("location-changed")));break;case"call-service":if(t.service&&this._hass){const[e,s]=t.service.split(".");this._hass.callService(e,s,t.service_data||{})}break;case"url":t.url_path&&window.open(t.url_path,"_blank")}}_setGlowIntensity(t,e,s){const i=this.renderRoot.querySelector(`#${t} .glow-ring`);if(!i)return;const r=Math.min(1,Math.abs(e)/s);i.style.opacity=(.15+.85*r).toFixed(2)}_animateValue(t,e,s=800,i=null){const r=this.renderRoot.getElementById(t);if(!r)return;this._animFrames[t]&&cancelAnimationFrame(this._animFrames[t]);const a=i||(t=>ut(t));if(null==e)return this._animFrames[t]&&(cancelAnimationFrame(this._animFrames[t]),delete this._animFrames[t]),this._currentValues[t]=null,void(r.textContent=a(null));const n=this._currentValues[t]||0;if(this._currentValues[t]=e,Math.abs(n-e)<.5)return void(r.textContent=a(e));const o=performance.now(),l=i=>{const c=Math.min(1,(i-o)/s),d=c<.5?2*c*c:1-Math.pow(-2*c+2,2)/2;r.textContent=a(n+(e-n)*d),c<1?this._animFrames[t]=requestAnimationFrame(l):delete this._animFrames[t]};this._animFrames[t]=requestAnimationFrame(l),setTimeout(()=>{this._currentValues[t]===e&&(this._animFrames[t]&&(cancelAnimationFrame(this._animFrames[t]),delete this._animFrames[t]),r.textContent=a(e))},s+250)}_setText(t,e){const s=this.renderRoot.getElementById(t);s&&(s.textContent=e)}_getState(t){if(!this._hass)return null;const e="prefix"===this._mode?`${this._prefix}${t}`:this._resolveEntity(t);return e?At(this._hass.states[e]):null}_isOut(t){const e=this._getEntityId(t);return!!e&&null==At(this._hass?.states[e])}_pairOut(t,e){return Bt(this._hass?.states,[this._getEntityId(t),this._getEntityId(e)])}_powerSnapshot(){if("prefix"!==this._mode||!this._hass)return null;const t=this._hass.states[this._prefix+"home_consumption_power"],e=t&&t.attributes&&t.attributes.power_snapshot;return e&&"object"==typeof e?e:null}_getStateStr(t){if(!this._hass)return"";const e="prefix"===this._mode?`${this._prefix}${t}`:this._resolveEntity(t);if(!e)return"";const s=this._hass.states[e];return s&&"unavailable"!==s.state&&"unknown"!==s.state?s.state:""}_getEntityId(t){return"prefix"===this._mode?`${this._prefix}${t}`:this._resolveEntity(t)}_resolveEntity(t){const e=this._entities;if(!e)return null;return{solar_power:e.solar?.entity,battery_power:e.battery?.entity,battery_charge_power:e.battery?.charge,battery_discharge_power:e.battery?.discharge,grid_power:e.grid?.entity,grid_import_power:e.grid?.consumption,grid_export_power:e.grid?.production,ev_power:e.ev?.entity||e.individual?.[0]?.entity,battery_soc:e.battery?.state_of_charge,home_consumption_power:e.home?.entity,charging_state:e.inverter?.entity,daily_solar_energy:e.solar?.daily_energy,daily_ev_energy:e.ev?.daily_energy||e.individual?.[0]?.daily_energy,daily_grid_import_energy:e.grid?.daily_import_energy,daily_grid_export_energy:e.grid?.daily_export_energy,daily_battery_energy:e.battery?.daily_energy,daily_home_energy:e.home?.daily_energy,autarky_rate:e.home?.autarky,ev_charger_count:e.ev?.charger_count||"sensor.sem_ev_charger_count"}[t]||null}_hasNode(t){if("ev"===t&&!this._showEv)return!1;if("battery"===t&&!this._showBattery)return!1;if("prefix"===this._mode)return!0;const e=this._entities;if(!e)return!1;return{solar:!!e.solar?.entity,battery:!!(e.battery?.entity||e.battery?.charge||e.battery?.discharge),grid:!(!e.grid?.consumption&&!e.grid?.entity),home:!0,ev:!(!e.ev?.entity&&!e.individual?.[0]?.entity),inverter:!!e.inverter?.entity||!!e.solar?.entity}[t]||!1}_getNodeColor(t){const e=this._entities,s={solar:Zi.solar.color,battery:Zi.battery.color,grid:Zi.grid.color_import,grid_import:Zi.grid.color_import,grid_export:Zi.grid.color_export,home:Zi.home.color,ev:Zi.ev.color,inverter:Zi.inverter.color};if(!e)return s[t]||"#888";return{solar:e.solar?.color,battery:e.battery?.color,grid:e.grid?.color_import,grid_import:e.grid?.color_import,grid_export:e.grid?.color_export,home:e.home?.color,ev:e.ev?.color||e.individual?.[0]?.color}[t]||s[t]||"#888"}_getNodeName(t){const e=this._entities,s=Zi[t]?.nameKey,i=s?this._t(s):t;if(!e)return i;return{solar:e.solar?.name,battery:e.battery?.name,grid:e.grid?.name,home:e.home?.name,ev:e.ev?.name||e.individual?.[0]?.name}[t]||i}_getLayout(){return this._compact?{vb:"0 0 500 1100",solar:{cx:250,cy:70,r:48},inverter:{cx:250,cy:225,r:20},battery:{cx:100,cy:340,r:48},grid:{cx:400,cy:340,r:48},home:{cx:250,cy:510,r:60},ev:{cx:100,cy:660,r:42},socR:33,autarkyR:48,paths:{solar:"M250,118 L250,205",home:"M250,245 L250,450",battery:"M230,230 C180,260 120,290 100,292",grid:"M270,230 C320,260 380,290 400,292",ev:"M230,240 C180,380 130,560 100,618"},font:{label:14,value:22,sub:12,homeVal:26},deviceY:810}:{vb:"0 0 1000 800",solar:{cx:500,cy:65,r:50},inverter:{cx:500,cy:210,r:20},battery:{cx:150,cy:270,r:50},grid:{cx:850,cy:270,r:50},home:{cx:500,cy:385,r:62},ev:{cx:150,cy:460,r:44},socR:40,autarkyR:50,paths:{solar:"M500,115 L500,190",home:"M500,230 L500,323",battery:"M480,215 C380,230 250,245 200,270",grid:"M520,215 C620,230 750,245 800,270",ev:"M480,225 C380,330 250,410 195,460"},font:{label:13,value:20,sub:11,homeVal:24},deviceY:590}}_glowFilter(t,e,s){return`<filter id="${t}" x="-30%" y="-30%" width="160%" height="160%">\n            <feGaussianBlur stdDeviation="${s}" result="blur"/>\n            <feFlood flood-color="${e}" flood-opacity="0.25"/>\n            <feComposite in2="blur" operator="in"/>\n            <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>\n        </filter>`}_glowRing(t,e,s=1.2){const i=t.r+5;return`<circle class="glow-ring" cx="${t.cx}" cy="${t.cy}" r="${i}" fill="none" stroke="${e}" stroke-width="${s}" opacity="0.3">\n            <animate attributeName="r" values="${i};${i+5};${i}" dur="3s" repeatCount="indefinite"/>\n            <animate attributeName="opacity" values="0.3;0.12;0.3" dur="3s" repeatCount="indefinite"/>\n        </circle>`}_track(t,e){return`<path d="${t}" fill="none" stroke="${e}" stroke-width="1.5" stroke-dasharray="4,6" opacity="0.18"/>`}_hexToRgba(t,e){const s=t.match(/^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);return s?`rgba(${parseInt(s[1],16)},${parseInt(s[2],16)},${parseInt(s[3],16)},${e})`:`rgba(128,128,128,${e})`}_autarkyColor(t){if((t=Math.max(0,Math.min(100,t)))<=50){const e=t/50;return`rgb(220,${Math.round(50+150*e)},50)`}const e=(t-50)/50;return`rgb(${Math.round(220-170*e)},200,50)`}_deviceIcon(t,e){const s=(e||"").toLowerCase();return"ev_charger"===(t||"").toLowerCase()||s.includes("keba")||s.includes("charger")||s.includes("wallbox")?'<rect x="-6" y="-10" width="12" height="16" rx="2"/><path d="M-2,-4 L0,2 L2,-4"/><line x1="0" y1="6" x2="0" y2="10"/>':s.includes("heiz")||s.includes("heat")||s.includes("warm")||s.includes("boiler")?'<path d="M-4,-10 C-4,-4 4,-4 4,-10"/><path d="M-4,-3 C-4,3 4,3 4,-3"/><path d="M-4,4 C-4,10 4,10 4,4"/>':s.includes("wash")||s.includes("spül")||s.includes("geschirr")||s.includes("wasch")?'<circle r="10" fill="none"/><circle r="5" fill="none"/><circle r="1.5" fill="currentColor" opacity="0.3" stroke="none"/>':s.includes("dryer")||s.includes("trockn")?'<circle r="10" fill="none"/><path d="M-4,-4 C0,-8 0,8 4,4" fill="none"/>':s.includes("pool")||s.includes("pump")?'<circle r="8" fill="none"/><path d="M-6,0 L6,0 M0,-6 L0,6" opacity="0.5"/><path d="M-4,-4 L4,4 M4,-4 L-4,4"/>':s.includes("klima")||s.includes("ac")||s.includes("cool")||s.includes("air")?'<rect x="-10" y="-6" width="20" height="12" rx="2"/><path d="M-6,6 C-6,10 -2,10 -2,6" fill="none"/><path d="M2,6 C2,10 6,10 6,6" fill="none"/>':s.includes("light")||s.includes("licht")||s.includes("lamp")?'<path d="M-5,-10 C-8,-2 -3,4 -2,6 L2,6 C3,4 8,-2 5,-10 C2,-14 -2,-14 -5,-10Z" fill="none"/><line x1="-2" y1="8" x2="2" y2="8"/>':s.includes("shelly")||s.includes("plug")||s.includes("switch")||s.includes("steckdose")?'<rect x="-8" y="-10" width="16" height="20" rx="3"/><circle cx="-3" cy="-2" r="2" fill="none"/><circle cx="3" cy="-2" r="2" fill="none"/><line x1="0" y1="4" x2="0" y2="7"/>':'<path d="M-3,-10 L-3,0 L-6,0 L0,10 L0,0 L3,0 L-3,-10Z" fill="none"/>'}getCardSize(){return 8}static async getConfigElement(){return document.createElement("sem-flow-card-editor")}static getStubConfig(t){const e=t?Object.keys(t.states):[],s=t=>{for(const s of t){const t=e.find(t=>t.includes(s));if(t)return t}return null};return{entities:{solar:{entity:s(["solar_power","pv_power"])||"sensor.solar_power"},grid:{consumption:s(["grid_import","grid_consumption"])||"sensor.grid_import_power",production:s(["grid_export","grid_feed"])||"sensor.grid_export_power"},battery:{entity:s(["battery_power","batt_power"])||"sensor.battery_power",state_of_charge:s(["battery_soc","battery_level"])||"sensor.battery_soc"},home:{entity:s(["home_consumption","house_power"])||"sensor.home_consumption_power"}}}}},{type:"sem-flow-card",name:"SEM Flow Card",description:"Animated energy flow diagram — works with any HA entities",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-flow-card"});const Xi=864e5,Ji=36e5;function Qi(t){const e=t?.state;if(null==e||""===e||"unavailable"===e||"unknown"===e)return null;const s=parseFloat(e);return!Number.isFinite(s)||s<0||s>100?null:s}function tr(t){const{soc:e,isEstimate:s}=t||{},i=It(e);return i.known?`${s?"~":""}${i.label}`:""}const er="sensor.sem_",sr=["solar_power","battery_power","grid_import_power","grid_export_power","ev_power","battery_soc","battery_temperature","charging_state","home_consumption_power","daily_solar_energy","daily_battery_charge_energy","daily_battery_discharge_energy","daily_ev_energy","daily_home_energy","daily_grid_import_energy","daily_grid_export_energy","forecast_today_kwh","controllable_devices_count"],ir=2551442889.6,rr=Date.parse("2000-01-06T18:14:00Z"),ar={new_moon:{k:0,waxing:!0},waxing_crescent:{k:.25,waxing:!0},first_quarter:{k:.5,waxing:!0},waxing_gibbous:{k:.75,waxing:!0},full_moon:{k:1,waxing:!0},waning_gibbous:{k:.75,waxing:!1},last_quarter:{k:.5,waxing:!1},waning_crescent:{k:.25,waxing:!1}};kt("sem-system-diagram-card",class extends Lt{static properties={_solarDisp:{state:!0},_battDisp:{state:!0},_homeDisp:{state:!0},_evDisp:{state:!0},_gridDisp:{state:!0},_gridDispMode:{state:!0},_sunTransform:{state:!0},_moonTransform:{state:!0},_sunPowerX:{state:!0},_sunPowerY:{state:!0},_sunPtX:{state:!0},_sunPtY:{state:!0}};static get watchedEntities(){return sr.map(t=>`${er}${t}`)}constructor(){super(),this._prefix=er,this._mode="prefix",this._entities=null,this._compact=!1,this._visible=!0,this._resizeObserver=null,this._intersectionObserver=null,this._resizeTimeout=null,this._counterRaf=null,this._targets=null,this._lastDiagKey="",this._sunSparkProps=null,this._sunSparkSig="",this._sparkWaveD=""}setConfig(t){super.setConfig(t),t.entities&&!t.entity_prefix?(this._mode="entities",this._entities=t.entities):(this._mode="prefix",this._entities=null),this._prefix=t.entity_prefix||er,this._showEv=!1!==t.show_ev,this._showBattery=!1!==t.show_battery,this._showEvSoc=!1!==t.show_ev_soc}_eid(t){if("entities"!==this._mode)return`${this._prefix}${t}`;const e=this._entities;if(!e)return null;return{solar_power:e.solar?.entity,battery_power:e.battery?.entity,battery_charge_power:e.battery?.charge,battery_discharge_power:e.battery?.discharge,grid_power:e.grid?.entity,grid_import_power:e.grid?.consumption,grid_export_power:e.grid?.production,ev_power:e.ev?.entity||e.individual?.[0]?.entity,battery_soc:e.battery?.state_of_charge,ev_soc:e.ev?.state_of_charge,battery_temperature:e.battery?.temperature,home_consumption_power:e.home?.entity,charging_state:e.inverter?.entity,daily_solar_energy:e.solar?.daily_energy,daily_ev_energy:e.ev?.daily_energy||e.individual?.[0]?.daily_energy,daily_grid_import_energy:e.grid?.daily_import_energy,daily_grid_export_energy:e.grid?.daily_export_energy,daily_battery_charge_energy:e.battery?.daily_charge_energy,daily_battery_discharge_energy:e.battery?.daily_discharge_energy,daily_home_energy:e.home?.daily_energy,autarky_rate:e.home?.autarky,self_consumption_rate:e.home?.self_consumption,forecast_today_kwh:e.solar?.forecast_remaining,controllable_devices_count:e.devices?.count_entity}[t]||null}_powerSnapshot(){if("prefix"!==this._mode||!this._hass)return null;const t=this._hass.states[this._prefix+"home_consumption_power"],e=t&&t.attributes&&t.attributes.power_snapshot;return e&&"object"==typeof e?e:null}_snapNum(t){const e=parseFloat(t);return isNaN(e)?0:e}_flowSolar(){const t=this._powerSnapshot();if(t)return this._snapNum(t.solar_w);const e=this._val("solar_power")??0;return this._entities?.solar?.reverse?-e:e}_flowBattery(){const t=this._entities;if(t?.battery?.charge||t?.battery?.discharge)return this._val("battery_charge_power",0)-this._val("battery_discharge_power",0);const e=this._powerSnapshot();if(e&&null!==e.battery_soc&&void 0!==e.battery_soc)return this._snapNum(e.battery_w);const s=this._val("battery_power",0);return t?.battery?.reverse?-s:s}_flowGridPair(){const t=this._entities;if("entities"===this._mode&&t?.grid?.entity){const e=this._state(t.grid.entity,0),s=t.grid.reverse;return{gridImport:Math.max(0,s?-e:e),gridExport:Math.max(0,s?e:-e)}}const e=this._powerSnapshot();return e?{gridImport:this._snapNum(e.grid_import_w),gridExport:this._snapNum(e.grid_export_w)}:{gridImport:this._val("grid_import_power",0),gridExport:this._val("grid_export_power",0)}}_flowEv(){const t=this._powerSnapshot();if(t)return this._snapNum(t.ev_w);const e=this._val("ev_power")??0;return this._entities?.ev?.invert?-e:e}_flowHome(t,e,s,i,r,a){const n=this._powerSnapshot();if(n&&null!==n.home_w&&void 0!==n.home_w)return Math.max(0,this._snapNum(n.home_w));const o=this._eid("home_consumption_power"),l=o?this._hass?.states[o]:null;if(l&&"unavailable"!==l.state&&"unknown"!==l.state){let t=this._state(o,0);return this._entities?.home?.invert&&(t=-t),Math.max(0,t)}return Math.max(0,t+e+r-s-i-a)}set hass(t){this._hass=t;const e=t?.language,s="function"==typeof semLocalize;let i=!1;if((e!==this._lang||s&&!this._localizeReady)&&(this._lang=e,this._localizeReady=s,i=!0),this._isFrozen()&&!i)return;if(!i&&"entities"!==this._mode&&Rt(t?.states,sr.map(t=>this._eid(t))))return;const r=sr.filter(t=>!(!this._showEv&&"ev_power"===t)&&!!(this._showBattery||"battery_power"!==t&&"battery_soc"!==t&&"battery_temperature"!==t));let a=r.map(e=>{const s=this._eid(e);return s&&t?.states[s]?.state||""}).join(",")+"|"+e;a+="|"+bt(t,this._prefix),this._showEv&&(a+="|"+(t?.states["binary_sensor.sem_ev_connected"]?.state||""),a+="|"+(t?.states["binary_sensor.sem_ev_charging"]?.state||""),a+="|"+this._evSocLabel(t));const n=t?.states["sun.sun"];if(a+="|"+(n?.attributes?.elevation??"")+":"+(n?.attributes?.next_rising||"")+":"+(n?.attributes?.next_setting||""),a+="|"+(t?.states["sensor.moon"]?.state||""),a===this._lastDiagKey&&!i)return;this._lastDiagKey=a;const o=this._flowSolar(),l=this._flowBattery(),c=Math.max(0,l),d=Math.max(0,-l),{gridImport:p,gridExport:_}=this._flowGridPair(),h=this._flowEv(),u=this._flowHome(o,p,_,c,d,h);this._targets={solar:o,batt:Math.abs(l),home:u,ev:h,grid:_>10?_:p>10?p:0,gridMode:_>10?"↑":p>10?"↓":null},this._startTickIfIdle(),this._scheduleUpdate()}get hass(){return this._hass}_val(t,e=null){const s=this._eid(t);return s?this._state(s,e):e}_rawOrMissing(t){const e=this._eid(t),s=e?this._hass?.states[e]:void 0;return Ft(s)?Nt:s.state}_valStr(t){const e=this._eid(t);return e?this._stateStr(e):""}_evSocLabel(t){const e=t?.states;if(!e||!this._showEvSoc)return"";if("entities"===this._mode){const t=this._eid("ev_soc");return t?tr({soc:Qi(e[t])}):""}return tr(function(t,e,s){if(1!==s.length)return{soc:null,isEstimate:!1};const i=s[0];return yi(Qi(t[`${e}charger_${i}_vehicle_soc`]),Qi(t[`${e}vehicle_soc`]),Qi(t[`${e}charger_${i}_estimated_soc`]),s.length)}(e,this._prefix,this._evChargerIds(e)))}_evChargerIds(t){const e=`${this._prefix}|${Object.keys(t).length}`;return e!==this._evIdsSig&&(this._evIdsSig=e,this._evIds=function(t,e){const s=`${e}charger_`,i=[];for(const e of t){if(!e.startsWith(s)||!e.endsWith("_power"))continue;if(e.includes("_flow_"))continue;const t=e.slice(s.length,e.length-6);t&&i.push(t)}return i}(Object.keys(t),this._prefix)),this._evIds}_unitStr(t){const e=this._eid(t);return e?this._unitOf(e):""}_readWithHold(t,e,s){const i=this._eid(t),r=i?this._hass?.states[i]:void 0,a=r?.state,n=r&&"unavailable"!==a&&"unknown"!==a,o=Date.now(),l=e+"Ts",c=e.startsWith("this.")?e.slice(5):e,d=l.startsWith("this.")?l.slice(5):l;if(n){const t=parseFloat(a);if(!Number.isNaN(t))return this[c]=t,this[d]=o,{value:t,stale:!1}}return null!=this[c]&&o-(this[d]||0)<s?{value:this[c],stale:!1}:{value:0,stale:!0}}_startTickIfIdle(){if(this._counterRaf)return;const t=(t,e)=>{const s=t??0,i=e-s;return Math.abs(i)<.5?e:s+.18*i},e=()=>{if(!this._targets)return void(this._counterRaf=null);const s=this._targets,i=t(this._solarDisp,s.solar),r=t(this._battDisp,s.batt),a=t(this._homeDisp,s.home),n=t(this._evDisp,s.ev),o=t(this._gridDisp,s.grid),l=i===s.solar&&r===s.batt&&a===s.home&&n===s.ev&&o===s.grid&&this._gridDispMode===s.gridMode;this._solarDisp=i,this._battDisp=r,this._homeDisp=a,this._evDisp=n,this._gridDisp=o,this._gridDispMode=s.gridMode,this._counterRaf=l?null:requestAnimationFrame(e)};this._counterRaf=requestAnimationFrame(e)}firstUpdated(){this.isConnected&&this._observe()}connectedCallback(){super.connectedCallback(),this.hasUpdated&&(this._observe(),this._targets&&this._startTickIfIdle())}_observe(){this._unobserve(),this._resizeObserver=new ResizeObserver(t=>{this._resizeTimeout&&clearTimeout(this._resizeTimeout),this._resizeTimeout=setTimeout(()=>{for(const e of t){const t=e.contentRect.width<500;t!==this._compact&&(this._compact=t,this._sunSparkSig="",this._lastDiagKey="",this.requestUpdate())}},100)}),this._resizeObserver.observe(this),this._intersectionObserver=new IntersectionObserver(t=>{this._visible=t[0].isIntersecting;const e=this.renderRoot.querySelector("svg");e&&(e.style.animationPlayState=this._visible?"running":"paused")},{threshold:.01}),this._intersectionObserver.observe(this)}_unobserve(){this._resizeObserver&&(this._resizeObserver.disconnect(),this._resizeObserver=null),this._intersectionObserver&&(this._intersectionObserver.disconnect(),this._intersectionObserver=null),clearTimeout(this._resizeTimeout)}disconnectedCallback(){super.disconnectedCallback(),this._unobserve(),this._counterRaf&&(cancelAnimationFrame(this._counterRaf),this._counterRaf=null)}updated(t){if(super.updated(t),!this._hass)return;const e=this.renderRoot.querySelector("#sun-arc-path");if(!e)return;const s=this._getLayout(),i=this._computeSunPose();try{const t=e.getTotalLength(),r=e.getPointAtLength(i.pos*t),a=r.x-s.sunX,n=r.y-s.sunY,o=`translate(${a.toFixed(1)},${n.toFixed(1)}) translate(${s.sunX},${s.sunY}) scale(${i.scale.toFixed(2)}) translate(${(-s.sunX).toFixed(1)},${(-s.sunY).toFixed(1)})`,l=i.isNight?`translate(${a.toFixed(1)},${n.toFixed(1)})`:"",c=r.x.toFixed(1),d=(r.y+s.sunR*i.scale+16).toFixed(1),p=+r.x.toFixed(1),_=+r.y.toFixed(1);if(this._sunTransform===o&&this._moonTransform===l&&this._sunPowerX===c&&this._sunPowerY===d&&this._sunPtX===p&&this._sunPtY===_)return;this._sunTransform=o,this._moonTransform=l,this._sunPowerX=c,this._sunPowerY=d,this._sunPtX=p,this._sunPtY=_}catch(t){}}_computeSunPose(){const t=this._hass?.states["sun.sun"],e=(t&&parseFloat(t.attributes?.elevation)||-90)<0,s=this._val("solar_power",0),i=t?.attributes;let r=.5;if(i){const t=i.next_rising?new Date(i.next_rising).getTime():0,s=i.next_setting?new Date(i.next_setting).getTime():0,a=Date.now();if(!e&&t&&s){const e=t-864e5,i=s-e;i>0&&(r=(a-e)/i)}else if(e&&t&&s){const e=function(t,e,s){if(!e||!s)return null;const i=s-t<Ji?s:s-Xi,r=e-t>828e5?e-Xi:e,a=r-i;return a<=0?Math.abs(t-r)<=Math.abs(t-i)?0:1:1-(t-i)/a}(a,t,s);null!==e&&(r=e)}else r=t&&a<t?0:1;r=Math.max(.06,Math.min(.94,r))}return{pos:r,scale:e?.7:.7+.6*Math.min(1,s/1e4),isNight:e,solar:s}}_computeMoonPhase(){const t=this._hass?.states["sensor.moon"]?.state;if(t&&ar[t])return ar[t];const e=((Date.now()-rr)%ir+ir)%ir/ir;return{k:(1-Math.cos(2*Math.PI*e))/2,waxing:e<.5}}_moonPhasePath(t,e,s){const i=s?1:0;return`M 0 ${-t} A ${t} ${t} 0 0 ${i} 0 ${t} A ${(t*Math.abs(1-2*e)).toFixed(2)} ${t} 0 0 ${e<.5?1-i:i} 0 ${-t} Z`}static get styles(){return a`
            :host { display: block; }
            ha-card { overflow: hidden; padding: 0; background: transparent !important; }
            svg { width: 100%; display: block; }
            .flow-group { transition: opacity 0.8s cubic-bezier(0.4,0,0.2,1); }
            .clickable { cursor: pointer; pointer-events: bounding-box; }
            .clickable:hover { filter: brightness(1.2); }
            text { font-variant-numeric: tabular-nums; }
            @media (prefers-reduced-motion: reduce) {
                .flow-group { transition: none; }
                animate, animateMotion { display: none; }
            }
        `}render(){if(!this._config)return K;const t=this._getLayout(),e=this._compact,s="'Segoe UI','Roboto',sans-serif",i=t.font.label,r=t.font.value,a=t.font.sub,n=this._flowSolar(),{gridImport:o,gridExport:l}=this._flowGridPair(),c=this._flowEv();let d,p;this._entities?.battery?.charge||this._entities?.battery?.discharge?(d=this._flowBattery(),p=Bt(this._hass?.states,[this._eid("battery_charge_power"),this._eid("battery_discharge_power")])):(({value:d,stale:p}=this._readWithHold("battery_power","this._lastBattPower",6e4)),this._entities?.battery?.reverse&&(d=-d));const{value:_,stale:h}=this._readWithHold("battery_soc","this._lastBattSoc",6e4),u=p||h,g=It(_,h),m=Math.max(0,d),f=Math.max(0,-d),y=this._flowHome(n,o,l,m,f,c),v=this._computeSunPose(),{isNight:b}=v,x=b?this._computeMoonPhase():{k:0,waxing:!0},$=b?.3:.85,w=n>50?Math.min(1,.3+n/5e3):0,k=this._hass?.states["sun.sun"]?.attributes,S=this._hass?.config?.time_zone||void 0,C=k?.next_rising?gt(k.next_rising,S):"",z=k?.next_setting?gt(k.next_setting,S):"",M=yt(this).isDark,D=M?"#FCD170":"#a06a00",E=M?.45:.8,N=M?"#ff9800":"#b35c00",F=M?.4:.8,A=M?"#96CAEE":"#3d6e94",T=M?.6:.85,I=M?.35:.8,R=t.B.r/50,B=64*R,O=B-12*R,L=t.B.cy-B/2+8*R,P=O*g.fraction,U=L+O-P,W=m>10?"#f06292":"url(#battFillGrad)",G=m>10,q=l>o?"#8353d1":"#488fc2",V=l>10&&l>o?this._t("exporting"):o>10?this._t("importing"):"",Y=l>10&&l>o?"#8353d1":"#488fc2",Z=m>10?"#f06292":"#4db6ac",X=m>10?this._t("charging"):f>10?this._t("discharging"):"",J=m>10?"#f06292":"#4db6ac",Q="on"===this._hass?.states["binary_sensor.sem_ev_connected"]?.state;let tt="",et="#8DC892";"on"===this._hass?.states["binary_sensor.sem_ev_charging"]?.state||c>10?(tt=this._t("charging"),et="#8DC892"):Q&&(tt=this._t("connected")||"Verbunden",et="rgba(141,200,146,0.6)");const st=this._showEv?this._evSocLabel(this._hass):"",it=this._t("today"),rt=`${it} ${this._rawOrMissing("daily_solar_energy")} kWh`,at=this._val("forecast_today_kwh"),nt=at>0?`☀ ${at.toFixed(1)} kWh ${this._t("forecast")||"Forecast"}`:"",ot=`${it} ${this._rawOrMissing("daily_ev_energy")} kWh`,lt=`${it} ${Tt(this._val("daily_home_energy"),1)} kWh`,ct=`+${Tt(this._val("daily_battery_charge_energy"),1)} / -${Tt(this._val("daily_battery_discharge_energy"),1)} kWh`,dt=`↓${Tt(this._val("daily_grid_import_energy"),1)} / ↑${Tt(this._val("daily_grid_export_energy"),1)} kWh`,pt=function(t,e,s={}){const{decimals:i=0,space:r=!1}=s;if(null==t||""===t||isNaN(parseFloat(t)))return"";const a=e||"°C";return`${parseFloat(t).toFixed(i)}${r?" ":""}${a}`}(this._valStr("inverter_temperature"),this._unitStr("inverter_temperature")),_t=this._valStr("charging_state"),ht=e?22:30,ft=_t.length>ht?_t.substring(0,ht-1)+"…":_t,vt=[],bt=["solar_power","grid_import_power","grid_export_power"];this._showBattery&&bt.push("battery_power","battery_soc"),this._showEv&&bt.push("ev_power");for(const t of bt){const e=this._eid(t);e?Ft(this._hass?.states[e])&&vt.push(t):"prefix"===this._mode&&vt.push(t)}const kt=new Set(vt),St=kt.has("solar_power"),Ct=this._hass?.states,zt="entities"===this._mode&&this._entities?.grid?.entity?Bt(Ct,[this._entities.grid.entity]):Bt(Ct,[this._eid("grid_import_power"),this._eid("grid_export_power")]),Mt=kt.has("ev_power"),Dt=this._powerSnapshot()?.home_w,Et=null==Dt&&Ft(this._hass?.states[this._eid("home_consumption_power")])&&(St||zt),Nt=ut(St?null:this._solarDisp??0),At=(m>10?"↑ ":f>10?"↓ ":"")+ut(this._battDisp??0),Rt=ut(Et?null:this._homeDisp??0),Ot=ut(Mt?null:this._evDisp??0),Lt=zt?ut(null):this._gridDispMode?`${this._gridDispMode} ${ut(this._gridDisp??0)}`:ut(0),Pt="↑"===this._gridDispMode?"#8353d1":"#488fc2",Ut=xt(this._hass,this._prefix),Wt=n>10,Ht=Math.abs(d)>10,jt=d<0,Gt=m>10?"#f06292":"#4db6ac",Kt=o>10||l>10,qt=o>l,Vt=l>o?"#8353d1":"#488fc2",Yt=y>10,Zt=c>10;return H`
            <ha-card>
                <style>${wt}</style>
                ${Ut.length>=2?H`
                    <div class="pv-strings-row">
                        ${Ut.map(t=>H`
                            <div class="pv-chip"
                                 title="${t.entityId}"
                                 data-entity="${t.entityId}"
                                 @click=${()=>this._fireMoreInfo(t.entityId)}>
                                <span class="pv-chip-label">${t.name}</span>
                                <span class="pv-chip-value">${$t(t.watts)}</span>
                            </div>
                        `)}
                    </div>
                `:K}
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="${t.vb}"
                     style="background:transparent;overflow:hidden"
                     role="img" aria-label="Solar energy system power flow diagram">
                    <defs>
                        <radialGradient id="bgGrad" cx="50%" cy="40%" r="65%">
                            <stop offset="0%" stop-color="rgba(150,202,238,0.06)"/>
                            <stop offset="100%" stop-color="rgba(0,0,0,0)"/>
                        </radialGradient>
                        <pattern id="dotGrid" width="40" height="40" patternUnits="userSpaceOnUse">
                            <circle cx="20" cy="20" r="0.6" fill="rgba(128,128,128,0.07)"/>
                        </pattern>

                        ${this._glowFilter("glowSolar","#ff9800",10)}
                        ${this._glowFilter("glowBattery","#4db6ac",8)}
                        ${this._glowFilter("glowGrid","#488fc2",8)}
                        ${this._glowFilter("glowHome","#5BC8D8",12)}
                        ${this._glowFilter("glowEV","#8DC892",8)}
                        ${this._glowFilter("glowInverter","#96CAEE",6)}
                        ${this._glowFilter("glowSun","#FCD170",14)}

                        <linearGradient id="panelBlue" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" stop-color="#1565C0" stop-opacity="0.9"/>
                            <stop offset="50%" stop-color="#1976D2" stop-opacity="0.8"/>
                            <stop offset="100%" stop-color="#0D47A1" stop-opacity="0.95"/>
                        </linearGradient>
                        <linearGradient id="panelBlue2" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" stop-color="#1E88E5" stop-opacity="0.85"/>
                            <stop offset="100%" stop-color="#1565C0" stop-opacity="0.9"/>
                        </linearGradient>
                        <linearGradient id="panelReflect" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="rgba(255,255,255,0.18)"/>
                            <stop offset="100%" stop-color="rgba(255,255,255,0)"/>
                        </linearGradient>

                        <linearGradient id="battBody" x1="0%" y1="0%" x2="100%" y2="0%">
                            <stop offset="0%" stop-color="#1a2e2c"/>
                            <stop offset="100%" stop-color="#1f3835"/>
                        </linearGradient>
                        <linearGradient id="battFillGrad" x1="0%" y1="100%" x2="0%" y2="0%">
                            <stop offset="0%" stop-color="#4db6ac"/>
                            <stop offset="100%" stop-color="#80cbc4"/>
                        </linearGradient>

                        <linearGradient id="roofGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#c62828"/>
                            <stop offset="100%" stop-color="#b71c1c"/>
                        </linearGradient>
                        <linearGradient id="wallGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#37474F"/>
                            <stop offset="100%" stop-color="#263238"/>
                        </linearGradient>
                        <radialGradient id="windowGlow" cx="50%" cy="50%" r="50%">
                            <stop offset="0%" stop-color="#FFF9C4" stop-opacity="0.9"/>
                            <stop offset="100%" stop-color="#F9A825" stop-opacity="0.3"/>
                        </radialGradient>

                        <linearGradient id="poleGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                            <stop offset="0%" stop-color="#5c7a9b"/>
                            <stop offset="50%" stop-color="#6d8fad"/>
                            <stop offset="100%" stop-color="#5c7a9b"/>
                        </linearGradient>

                        <linearGradient id="invGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#1a2740"/>
                            <stop offset="100%" stop-color="#0f1820"/>
                        </linearGradient>

                        <linearGradient id="carGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#2e5a3c"/>
                            <stop offset="100%" stop-color="#1b3b27"/>
                        </linearGradient>

                        <radialGradient id="sunGradInner" cx="50%" cy="50%" r="50%">
                            <stop offset="0%" stop-color="#FFF9C4"/>
                            <stop offset="60%" stop-color="#FCD170"/>
                            <stop offset="100%" stop-color="#F7941E"/>
                        </radialGradient>

                        ${null!=this._sunPtX&&n>50?this._sparkWavePath(t):K}
                    </defs>

                    <rect width="100%" height="100%" fill="url(#bgGrad)"/>
                    <rect width="100%" height="100%" fill="url(#dotGrid)"/>

                    <!-- Sun arc group -->
                    <g>
                        <path id="sun-arc-path" d="${t.sunArc}" fill="none" stroke="rgba(252,209,112,0.12)"
                              stroke-width="2" stroke-dasharray="4,8"/>
                        <text x="${t.sunRisingX}" y="${t.sunLabelY}"
                              text-anchor="middle" font-family="${s}" font-size="${a}"
                              fill="${D}" opacity="${E}">${C}</text>
                        <text x="${t.sunSettingX}" y="${t.sunLabelY}"
                              text-anchor="middle" font-family="${s}" font-size="${a}"
                              fill="${D}" opacity="${E}">${z}</text>

                        <g filter="url(#glowSun)" style="opacity:${$}"
                           transform="${this._sunTransform??""}">
                            <circle cx="${t.sunX}" cy="${t.sunY}" r="${t.sunR+6}"
                                    fill="rgba(252,209,112,0.15)"/>
                            ${this._sunRays(t.sunX,t.sunY,t.sunR)}
                            <circle cx="${t.sunX}" cy="${t.sunY}" r="${t.sunR}"
                                    fill="url(#sunGradInner)"/>
                            <ellipse cx="${t.sunX-.25*t.sunR}" cy="${t.sunY-.28*t.sunR}"
                                     rx="${.35*t.sunR}" ry="${.22*t.sunR}"
                                     fill="rgba(255,255,255,0.35)"/>
                        </g>

                        <g style="display:${b?"block":"none"}"
                           transform="${this._moonTransform??""}">
                            <circle cx="${t.sunX}" cy="${t.sunY}" r="${t.sunR}" fill="#1a2540"/>
                            ${x.k>.03?j`<circle cx="${t.sunX}" cy="${t.sunY}"
                                    r="${(t.sunR+3+5*x.k).toFixed(1)}" fill="none"
                                    stroke="rgba(240,236,216,${(.09*x.k).toFixed(2)})"
                                    stroke-width="4"/>`:K}
                            <g transform="translate(${t.sunX},${t.sunY})">
                                <path d="${this._moonPhasePath(t.sunR,x.k,x.waxing)}"
                                      fill="#f0ecd8"/>
                            </g>
                            <circle cx="${t.sunX}" cy="${t.sunY}" r="${t.sunR}"
                                    fill="none" stroke="rgba(200,220,255,0.5)" stroke-width="1"/>
                        </g>

                        <g style="display:${b?"block":"none"}" fill="rgba(200,220,255,0.6)">
                            <circle cx="${t.starX[0]}" cy="${t.starY[0]}" r="1.2"/>
                            <circle cx="${t.starX[1]}" cy="${t.starY[1]}" r="0.9"/>
                            <circle cx="${t.starX[2]}" cy="${t.starY[2]}" r="1.4"/>
                            <circle cx="${t.starX[3]}" cy="${t.starY[3]}" r="0.8"/>
                            <circle cx="${t.starX[4]}" cy="${t.starY[4]}" r="1.1"/>
                        </g>

                        <text x="${this._sunPowerX??t.sunX}" y="${this._sunPowerY??t.sunY+t.sunR+14}"
                              text-anchor="middle" font-family="${s}" font-size="${a}"
                              fill="#FCD170" opacity="0.7" font-weight="600">${n>10?ut(n):""}</text>

                        <g style="opacity:${w}">
                            ${null!=this._sunPtX&&n>50?this._renderSunSpark(n):K}
                        </g>
                    </g>

                    <!-- Static dashed flow tracks -->
                    <path d="${t.paths.solar}"   fill="none" stroke="#ff9800" stroke-width="2"
                          stroke-dasharray="5,7" opacity="0.22"/>
                    <path d="${t.paths.home}"    fill="none" stroke="#5BC8D8" stroke-width="2"
                          stroke-dasharray="5,7" opacity="0.22"/>
                    ${this._showBattery?j`<path d="${t.paths.battery}" fill="none" stroke="#4db6ac" stroke-width="2"
                          stroke-dasharray="5,7" opacity="0.22"/>`:K}
                    <path d="${t.paths.grid}"    fill="none" stroke="#488fc2" stroke-width="2"
                          stroke-dasharray="5,7" opacity="0.22"/>
                    ${this._showEv?j`<path d="${t.paths.ev}" fill="none" stroke="#8DC892" stroke-width="2"
                          stroke-dasharray="5,7" opacity="0.22"/>`:K}

                    <!-- Flow animation groups -->
                    <g class="flow-group" style="opacity:${Wt?1:0}">
                        ${this._renderFlow(!1,"#ff9800",mt(n),t.paths.solar,2)}
                    </g>
                    ${this._showBattery?j`<g class="flow-group" style="opacity:${Ht?1:0}">
                        ${this._renderFlow(jt,Gt,mt(d),t.paths.battery,3)}
                    </g>`:K}
                    <g class="flow-group" style="opacity:${Kt?1:0}">
                        ${this._renderFlow(qt,Vt,mt(o||l),t.paths.grid,3)}
                    </g>
                    <g class="flow-group" style="opacity:${Yt?1:0}">
                        ${this._renderFlow(!1,"#5BC8D8",mt(y),t.paths.home,2)}
                    </g>
                    ${this._showEv?j`<g class="flow-group" style="opacity:${Zt?1:0}">
                        ${this._renderFlow(!1,"#8DC892",mt(c),t.paths.ev,3)}
                    </g>`:K}

                    <!-- Solar panel -->
                    <g filter="url(#glowSolar)" class="clickable" @click=${()=>this._showMoreInfo("solar_power")}>
                        ${this._illustrationSolarPanel(t.S.cx,t.S.cy,t.S.r)}
                    </g>
                    <text x="${t.S.cx}" y="${t.S.labelY}" text-anchor="middle"
                          font-family="${s}" font-size="${i}" font-weight="700"
                          fill="#ff9800" letter-spacing="0.5">${this._t("solar")}</text>
                    <text x="${t.S.cx}" y="${t.S.labelY+1.1*r}" class="clickable"
                          @click=${()=>this._showMoreInfo("solar_power")}
                          text-anchor="middle" font-family="${s}" font-size="${r}"
                          font-weight="800" fill="#ff9800">${Nt}</text>
                    <text x="${t.S.cx}" y="${t.S.labelY+1.1*r+a+3}" class="clickable"
                          @click=${()=>this._showMoreInfo("daily_solar_energy")}
                          text-anchor="middle" font-family="${s}" font-size="${a+1}"
                          fill="#ff9800" opacity="0.6" font-weight="600">${rt}</text>
                    <text x="${t.S.cx}" y="${t.S.labelY+1.1*r+2*(a+3)}" class="clickable"
                          @click=${()=>this._showMoreInfo("forecast_today_kwh")}
                          text-anchor="middle" font-family="${s}" font-size="${a}"
                          fill="${N}" opacity="${F}" font-weight="500">${nt}</text>

                    <!-- Inverter -->
                    <g filter="url(#glowInverter)">
                        ${this._illustrationInverter(t.I.cx,t.I.cy,t.I.r)}
                    </g>
                    <text x="${t.I.cx}" y="${t.I.cy+t.I.r+14}"
                          text-anchor="middle" font-family="${s}" font-size="${a}"
                          fill="${A}" opacity="${T}" font-weight="600">${pt}</text>
                    <text x="${t.I.cx}" y="${t.I.cy+t.I.r+14+a+2}"
                          text-anchor="middle" font-family="${s}" font-size="${a-1}"
                          fill="${A}" opacity="${I}">${ft}</text>

                    <!-- Battery (omitted entirely when show_battery: false,
                         #614 — the ghost-node class's battery sibling).
                         Group opacity fades to 0.35 if both
                         battery_soc and battery_power have been
                         unavailable for >60 s (Huawei modbus hard
                         dropout). Brief flickers (<60 s) are absorbed
                         by '_readWithHold' upstream so the user
                         doesn't see a visual emergency. (NEVER put
                         backticks inside this lit template's COMMENTS:
                         they terminate the template literal and the whole
                         card renders blank, #488.) -->
                    ${this._showBattery?j`<g filter="url(#glowBattery)" class="clickable"
                       opacity="${u?.35:1}"
                       @click=${()=>this._showMoreInfo("battery_soc")}>
                        ${this._illustrationBattery(t.B.cx,t.B.cy,t.B.r,P,U,W,G,g.label)}
                    </g>
                    <text x="${t.B.cx}" y="${t.B.labelY}" text-anchor="middle"
                          font-family="${s}" font-size="${i}" font-weight="700"
                          fill="#4db6ac" letter-spacing="0.5">${this._t("battery")}</text>
                    <text x="${t.B.cx}" y="${t.B.labelY+1*r}" class="clickable"
                          @click=${()=>this._showMoreInfo("battery_power")}
                          text-anchor="middle" font-family="${s}" font-size="${r}"
                          font-weight="800" fill="${Z}"
                          opacity="${u?.4:1}">${u?"— W":At}</text>
                    <text x="${t.B.cx}" y="${t.B.labelY+1*r+i}"
                          text-anchor="middle" font-family="${s}" font-size="${i}"
                          fill="${J}" opacity="0.6">${u?this._t("sensor_unavailable"):X}</text>
                    <text x="${t.B.cx}" y="${t.B.labelY+1*r+i+a+2}" class="clickable"
                          @click=${()=>this._showMoreInfo("daily_battery_charge_energy")}
                          text-anchor="middle" font-family="${s}" font-size="${a+1}"
                          fill="#4db6ac" opacity="0.6" font-weight="600">${ct}</text>`:K}

                    <!-- Grid -->
                    <g filter="url(#glowGrid)" class="clickable" @click=${()=>this._showMoreInfo("grid_import_power")}>
                        ${this._illustrationGrid(t.G.cx,t.G.cy,t.G.r)}
                    </g>
                    <text x="${t.G.cx}" y="${t.G.labelY}" text-anchor="middle"
                          font-family="${s}" font-size="${i}" font-weight="700"
                          fill="${q}" letter-spacing="0.5">${this._t("grid")}</text>
                    <text x="${t.G.cx}" y="${t.G.labelY+r}" class="clickable"
                          @click=${()=>this._showMoreInfo("grid_power")}
                          text-anchor="middle" font-family="${s}" font-size="${r}"
                          font-weight="800" fill="${Pt}">${Lt}</text>
                    <text x="${t.G.cx}" y="${t.G.labelY+r+i+1}"
                          text-anchor="middle" font-family="${s}" font-size="${i}"
                          fill="${Y}" opacity="0.6">${V}</text>
                    <text x="${t.G.cx}" y="${t.G.labelY+r+i+a+4}" class="clickable"
                          @click=${()=>this._showMoreInfo("daily_grid_import_energy")}
                          text-anchor="middle" font-family="${s}" font-size="${a+1}"
                          fill="#488fc2" opacity="0.6" font-weight="600">${dt}</text>

                    <!-- House -->
                    <g filter="url(#glowHome)" class="clickable" @click=${()=>this._showMoreInfo("home_consumption_power")}>
                        ${this._illustrationHouse(t.H.cx,t.H.cy,t.H.r)}
                    </g>
                    <text x="${t.H.cx}" y="${t.H.labelY}" text-anchor="middle"
                          font-family="${s}" font-size="${i}" font-weight="700"
                          fill="#5BC8D8" letter-spacing="0.5">${this._t("home")}</text>
                    <text x="${t.H.cx}" y="${t.H.labelY+1.1*r}" class="clickable"
                          @click=${()=>this._showMoreInfo("home_consumption_power")}
                          text-anchor="middle" font-family="${s}" font-size="${r}"
                          font-weight="800" fill="#5BC8D8">${Rt}</text>
                    <text x="${t.H.cx}" y="${t.H.labelY+1.1*r+a+3}" class="clickable"
                          @click=${()=>this._showMoreInfo("daily_home_energy")}
                          text-anchor="middle" font-family="${s}" font-size="${a+1}"
                          fill="#5BC8D8" opacity="0.6" font-weight="600">${lt}</text>

                    <!-- EV (omitted entirely when show_ev: false, #595) -->
                    ${this._showEv?j`<g filter="url(#glowEV)" class="clickable" @click=${()=>this._showMoreInfo("ev_power")}>
                        ${this._illustrationEV(t.E.cx,t.E.cy,t.E.r)}
                    </g>
                    <text x="${t.E.cx}" y="${t.E.labelY}" text-anchor="middle"
                          font-family="${s}" font-size="${i}" font-weight="700"
                          fill="#8DC892" letter-spacing="0.5">${this._t("ev_charging")}</text>
                    <text x="${t.E.cx}" y="${t.E.labelY+1*r}" class="clickable"
                          @click=${()=>this._showMoreInfo("ev_power")}
                          text-anchor="middle" font-family="${s}" font-size="${r}"
                          font-weight="800" fill="#8DC892">${Ot}</text>
                    <text x="${t.E.cx}" y="${t.E.labelY+1*r+i}"
                          text-anchor="middle" font-family="${s}" font-size="${i}"
                          fill="${et}" fill-opacity="0.6">${tt}${st?j`${tt?" · ":""}<tspan fill="#8DC892" fill-opacity="1" font-weight="800">${st}</tspan>`:K}</text>
                    <text x="${t.E.cx}" y="${t.E.labelY+1*r+i+a+2}" class="clickable"
                          @click=${()=>this._showMoreInfo("daily_ev_energy")}
                          text-anchor="middle" font-family="${s}" font-size="${a+1}"
                          fill="#8DC892" opacity="0.6" font-weight="600">${ot}</text>`:K}

                    <!-- Device strip (desktop only) -->
                    ${e?K:this._renderDeviceStrip(t.H)}

                    <!-- Entity status indicator -->
                    ${vt.length>0?H`
                        <foreignObject x="${e?8:10}" y="${t.statusY}" width="220" height="22">
                            <div xmlns="http://www.w3.org/1999/xhtml"
                                 style="font-family:'Segoe UI','Roboto',sans-serif;font-size:11px;color:#ef5350;opacity:0.75;white-space:nowrap">⚠ ${vt.length} ${this._t("sensor_unavailable")}</div>
                        </foreignObject>
                    `:K}

                    <text x="${t.wmX}" y="${t.wmY}" text-anchor="end"
                          font-family="${s}" font-size="9" font-weight="300"
                          letter-spacing="2.5" fill="rgba(255,255,255,0.06)">SEM</text>
                </svg>
                ${e?this._renderDeviceChips():K}
            </ha-card>
        `}_illustrationSolarPanel(t,e,s){const i=s/50,r=86*i,a=58*i,n=t-r/2,o=e-a/2-4*i,l=r/3,c=a/2,d=6*i,p=12*i;return j`
            <circle cx="${t}" cy="${e}" r="${s+4}" fill="none"
                    stroke="#ff9800" stroke-width="1.2" opacity="0.25"/>

            <line x1="${n+d}" y1="${o+a}" x2="${n+d-4*i}" y2="${o+a+p}"
                  stroke="#ff9800" stroke-width="${2*i}" stroke-linecap="round" opacity="0.7"/>
            <line x1="${n+r-d}" y1="${o+a}" x2="${n+r-d+4*i}" y2="${o+a+p}"
                  stroke="#ff9800" stroke-width="${2*i}" stroke-linecap="round" opacity="0.7"/>
            <line x1="${n+r/2}" y1="${o+a}" x2="${n+r/2}" y2="${o+a+.8*p}"
                  stroke="#ff9800" stroke-width="${1.5*i}" stroke-linecap="round" opacity="0.5"/>
            <line x1="${n+d-6*i}" y1="${o+a+p}"
                  x2="${n+r-d+6*i}" y2="${o+a+p}"
                  stroke="#ff9800" stroke-width="${2.5*i}" stroke-linecap="round" opacity="0.6"/>

            <line x1="${n}" y1="${o+.52*a}" x2="${n+r}" y2="${o+.52*a}"
                  stroke="#ff9800" stroke-width="${2*i}" opacity="0.5"/>
            <line x1="${n}" y1="${o}" x2="${n+r}" y2="${o}"
                  stroke="#ff9800" stroke-width="${2*i}" opacity="0.5"/>

            <rect x="${n}"        y="${o}"      width="${l}" height="${c}" fill="url(#panelBlue)"  rx="${1*i}"/>
            <rect x="${n+l}"   y="${o}"      width="${l}" height="${c}" fill="url(#panelBlue2)" rx="${1*i}"/>
            <rect x="${n+2*l}" y="${o}"      width="${l}" height="${c}" fill="url(#panelBlue)"  rx="${1*i}"/>
            <rect x="${n}"        y="${o+c}" width="${l}" height="${c}" fill="url(#panelBlue2)" rx="${1*i}"/>
            <rect x="${n+l}"   y="${o+c}" width="${l}" height="${c}" fill="url(#panelBlue)"  rx="${1*i}"/>
            <rect x="${n+2*l}" y="${o+c}" width="${l}" height="${c}" fill="url(#panelBlue2)" rx="${1*i}"/>

            <line x1="${n+l}"   y1="${o}" x2="${n+l}"   y2="${o+a}" stroke="rgba(0,0,0,0.4)" stroke-width="${1.5*i}"/>
            <line x1="${n+2*l}" y1="${o}" x2="${n+2*l}" y2="${o+a}" stroke="rgba(0,0,0,0.4)" stroke-width="${1.5*i}"/>
            <line x1="${n}" y1="${o+c}" x2="${n+r}" y2="${o+c}" stroke="rgba(0,0,0,0.4)" stroke-width="${1.5*i}"/>
            ${[0,1,2].map(t=>j`
                <line x1="${n+t*l+l/3}"   y1="${o}" x2="${n+t*l+l/3}"   y2="${o+a}" stroke="rgba(0,0,0,0.2)" stroke-width="${.7*i}"/>
                <line x1="${n+t*l+2*l/3}" y1="${o}" x2="${n+t*l+2*l/3}" y2="${o+a}" stroke="rgba(0,0,0,0.2)" stroke-width="${.7*i}"/>
            `)}
            <line x1="${n}" y1="${o+c/3}"   x2="${n+r}" y2="${o+c/3}"   stroke="rgba(0,0,0,0.18)" stroke-width="${.7*i}"/>
            <line x1="${n}" y1="${o+2*c/3}" x2="${n+r}" y2="${o+2*c/3}" stroke="rgba(0,0,0,0.18)" stroke-width="${.7*i}"/>

            <rect x="${n}" y="${o}" width="${r}" height="${a}"
                  fill="none" stroke="#ff9800" stroke-width="${2*i}" rx="${1.5*i}" opacity="0.8"/>

            <rect x="${n}" y="${o}" width="${r}" height="${.45*a}"
                  fill="url(#panelReflect)" rx="${1.5*i}" opacity="0.5"/>

            <circle cx="${t}" cy="${o+a+p+3*i}" r="${3*i}"
                    fill="#ff9800" opacity="0.6"/>
        `}_sunRays(t,e,s){const i=[];for(let r=0;r<8;r++){const a=45*r*Math.PI/180,n=s+3,o=s+.7*s,l=.18,c=a-l,d=a+l,p=t+Math.cos(c)*n,_=e+Math.sin(c)*n,h=t+Math.cos(a)*o,u=e+Math.sin(a)*o,g=t+Math.cos(d)*n,m=e+Math.sin(d)*n;i.push(j`<polygon points="${p},${_} ${h},${u} ${g},${m}"
                                    fill="#FCD170" opacity="0.85"/>`)}return i}_illustrationInverter(t,e,s){const i=s/20,r=38*i,a=28*i,n=t-r/2,o=e-a/2;return j`
            <rect x="${n}" y="${o}" width="${r}" height="${a}" rx="${4*i}"
                  fill="url(#invGrad)" stroke="#96CAEE" stroke-width="${1.5*i}" opacity="0.9"/>
            ${[0,1,2].map(t=>j`
                <line x1="${n+4*i+5*t*i}" y1="${o+3*i}" x2="${n+4*i+5*t*i}" y2="${o+7*i}"
                      stroke="#96CAEE" stroke-width="${1*i}" stroke-linecap="round" opacity="0.4"/>
            `)}
            <text x="${t-8*i}" y="${e+2*i}" font-family="'Segoe UI',sans-serif"
                  font-size="${7*i}" fill="#96CAEE" opacity="0.8" text-anchor="middle">DC</text>
            <path d="M${t-1*i},${e-4*i} L${t-3*i},${e+1*i} L${t},${e+1*i}
                     L${t},${e+5*i} L${t+2*i},${e} L${t-1*i},${e}"
                  fill="#FCD170" opacity="0.85"/>
            <text x="${t+8*i}" y="${e+2*i}" font-family="'Segoe UI',sans-serif"
                  font-size="${7*i}" fill="#96CAEE" opacity="0.8" text-anchor="middle">AC</text>
            <circle cx="${n+r-5*i}" cy="${o+4*i}" r="${2.5*i}"
                    fill="#69f0ae" opacity="0.9">
                <animate attributeName="opacity" values="0.9;0.4;0.9" dur="2.5s" repeatCount="indefinite"/>
            </circle>
            <rect x="${t-3*i}" y="${o+a}" width="${6*i}" height="${3*i}" rx="${1*i}"
                  fill="#96CAEE" opacity="0.4"/>
        `}_illustrationBattery(t,e,s,i,r,a,n,o){const l=s/50,c=40*l,d=64*l,p=t-c/2,_=e-d/2,h=8*l,u=16*l,g=c-8*l,m=d-12*l,f=p+4*l,y=_+8*l;return j`
            <circle cx="${t}" cy="${e}" r="${s+4}" fill="none"
                    stroke="#4db6ac" stroke-width="1.2" opacity="0.25"/>

            <rect x="${t-u/2}" y="${_-h}" width="${u}" height="${h}"
                  rx="${3*l}" fill="#2a4a47" stroke="#4db6ac" stroke-width="${1.5*l}" opacity="0.85"/>
            <line x1="${t-u/4}" y1="${_-h/2}"
                  x2="${t+u/4}" y2="${_-h/2}"
                  stroke="#4db6ac" stroke-width="${2*l}" stroke-linecap="round" opacity="0.8"/>
            <line x1="${t}" y1="${_-.75*h}" x2="${t}" y2="${_-.25*h}"
                  stroke="#4db6ac" stroke-width="${2*l}" stroke-linecap="round" opacity="0.8"/>

            <rect x="${p}" y="${_}" width="${c}" height="${d}" rx="${5*l}"
                  fill="url(#battBody)" stroke="#4db6ac" stroke-width="${2*l}" opacity="0.95"/>

            <rect x="${f}" y="${y}" width="${g}" height="${m}"
                  rx="${3*l}" fill="rgba(0,0,0,0.4)"/>

            <rect x="${f}" y="${r.toFixed(1)}"
                  width="${g}" height="${i.toFixed(1)}"
                  rx="${3*l}" fill="${a}" opacity="0.85"/>

            ${[1,2,3,4].map(t=>j`
                <line x1="${f}" y1="${y+m*t/5}"
                      x2="${f+g}" y2="${y+m*t/5}"
                      stroke="rgba(0,0,0,0.35)" stroke-width="${1.2*l}"/>
            `)}

            <text x="${t}" y="${n?e+15*l:e+4*l}"
                  text-anchor="middle" font-family="'Segoe UI','Roboto',sans-serif"
                  font-size="${14*l}" font-weight="900" fill="#fff"
                  stroke="rgba(0,0,0,0.6)" stroke-width="${1.5*l}" paint-order="stroke">${o}</text>

            ${n?j`
                <g>
                    <path d="M${t-4*l},${e-9*l-8*l} L${t-7*l},${e-9*l+2*l} L${t-1*l},${e-9*l+2*l}
                             L${t-1*l},${e-9*l+10*l} L${t+6*l},${e-9*l-2*l} L${t+1*l},${e-9*l-2*l} Z"
                          fill="#FCD170" opacity="0.95"/>
                </g>
            `:K}

            <rect x="${t-10*l}" y="${_+d-5*l}" width="${20*l}" height="${5*l}"
                  rx="${2*l}" fill="#4db6ac" opacity="0.25"/>
        `}_illustrationHouse(t,e,s){const i=s/62,r=80*i,a=52*i,n=t-r/2,o=e-a/2+8*i,l=o-38*i,c=t+18*i,d=l+8*i,p=10*i,_=18*i,h=16*i,u=14*i,g=o+12*i,m=n+10*i,f=n+r-10*i-h,y=14*i,v=24*i,b=t-y/2,x=o+a-v;return j`
            <circle cx="${t}" cy="${e}" r="${s+4}" fill="none"
                    stroke="#5BC8D8" stroke-width="1.2" opacity="0.25"/>

            <rect x="${c}" y="${d-_}" width="${p}" height="${_}"
                  rx="${2*i}" fill="#455A64" stroke="#546E7A" stroke-width="${1.2*i}"/>
            <circle cx="${c+p/2}" cy="${d-_-5*i}" r="${3*i}"
                    fill="rgba(150,160,170,0.3)"/>
            <circle cx="${c+p/2+2*i}" cy="${d-_-10*i}" r="${2.5*i}"
                    fill="rgba(150,160,170,0.2)"/>

            <polygon points="${n},${o} ${n+r},${o} ${t},${l}"
                     fill="url(#roofGrad)" stroke="#c62828" stroke-width="${1.5*i}"
                     stroke-linejoin="round"/>
            <line x1="${t-18*i}" y1="${l+10*i}" x2="${t+18*i}" y2="${l+10*i}"
                  stroke="rgba(255,255,255,0.12)" stroke-width="${1*i}"/>
            <line x1="${n-3*i}" y1="${o}" x2="${n+r+3*i}" y2="${o}"
                  stroke="#7f1010" stroke-width="${3*i}" opacity="0.5"/>

            <rect x="${n}" y="${o}" width="${r}" height="${a}"
                  rx="${2*i}" fill="url(#wallGrad)"
                  stroke="#546E7A" stroke-width="${1.5*i}"/>

            <rect x="${m-2*i}" y="${g-2*i}" width="${h+4*i}" height="${u+4*i}"
                  rx="${2*i}" fill="#2d3c45" stroke="#5BC8D8" stroke-width="${1.2*i}" opacity="0.9"/>
            <rect x="${m}" y="${g}" width="${h}" height="${u}"
                  rx="${1.5*i}" fill="url(#windowGlow)" opacity="0.85"/>
            <line x1="${m+h/2}" y1="${g}" x2="${m+h/2}" y2="${g+u}"
                  stroke="rgba(50,50,60,0.6)" stroke-width="${1.2*i}"/>
            <line x1="${m}" y1="${g+u/2}" x2="${m+h}" y2="${g+u/2}"
                  stroke="rgba(50,50,60,0.6)" stroke-width="${1.2*i}"/>

            <rect x="${f-2*i}" y="${g-2*i}" width="${h+4*i}" height="${u+4*i}"
                  rx="${2*i}" fill="#2d3c45" stroke="#5BC8D8" stroke-width="${1.2*i}" opacity="0.9"/>
            <rect x="${f}" y="${g}" width="${h}" height="${u}"
                  rx="${1.5*i}" fill="url(#windowGlow)" opacity="0.85"/>
            <line x1="${f+h/2}" y1="${g}" x2="${f+h/2}" y2="${g+u}"
                  stroke="rgba(50,50,60,0.6)" stroke-width="${1.2*i}"/>
            <line x1="${f}" y1="${g+u/2}" x2="${f+h}" y2="${g+u/2}"
                  stroke="rgba(50,50,60,0.6)" stroke-width="${1.2*i}"/>

            <rect x="${b}" y="${x}" width="${y}" height="${v}"
                  rx="${2*i}" fill="#506C7F" stroke="#5BC8D8" stroke-width="${1.2*i}" opacity="0.9"/>
            <rect x="${b+.15*y}" y="${x+4*i}"
                  width="${.7*y}" height="${.35*v}"
                  rx="${1.5*i}" fill="url(#windowGlow)" opacity="0.6"/>
            <circle cx="${b+.75*y}" cy="${x+.62*v}" r="${1.5*i}"
                    fill="#FCD170" opacity="0.8"/>

            <line x1="${n+2*i}" y1="${o+4*i}" x2="${n+2*i}" y2="${o+a-2*i}"
                  stroke="rgba(255,255,255,0.06)" stroke-width="${1.5*i}"/>
        `}_illustrationGrid(t,e,s){const i=s/50,r=72*i,a=4*i,n=e-r/2+4*i,o=n+.22*r,l=n+.42*r,c=44*i,d=32*i,p=3*i;return j`
            <circle cx="${t}" cy="${e}" r="${s+4}" fill="none"
                    stroke="#488fc2" stroke-width="1.2" opacity="0.25"/>

            <polygon points="${t-a/2},${n+r}
                             ${t+a/2},${n+r}
                             ${t+.35*a},${n}
                             ${t-.35*a},${n}"
                     fill="url(#poleGrad)" stroke="#5c7a9b" stroke-width="${1*i}"/>

            <rect x="${t-8*i}" y="${n+r-4*i}"
                  width="${16*i}" height="${4*i}" rx="${2*i}"
                  fill="#5c7a9b" opacity="0.6"/>

            <rect x="${t-c/2}" y="${o-3*i}" width="${c}" height="${5*i}"
                  rx="${2*i}" fill="url(#poleGrad)" stroke="#5c7a9b" stroke-width="${.8*i}"/>
            <line x1="${t}" y1="${o+2*i}"
                  x2="${t-.4*c}" y2="${o+14*i}"
                  stroke="#5c7a9b" stroke-width="${2*i}" opacity="0.5"/>
            <line x1="${t}" y1="${o+2*i}"
                  x2="${t+.4*c}" y2="${o+14*i}"
                  stroke="#5c7a9b" stroke-width="${2*i}" opacity="0.5"/>

            <rect x="${t-d/2}" y="${l-3*i}" width="${d}" height="${5*i}"
                  rx="${2*i}" fill="url(#poleGrad)" stroke="#5c7a9b" stroke-width="${.8*i}"/>

            <circle cx="${t-c/2}" cy="${o}" r="${p}"
                    fill="#838bc5" stroke="#488fc2" stroke-width="${1*i}"/>
            <circle cx="${t+c/2}" cy="${o}" r="${p}"
                    fill="#838bc5" stroke="#488fc2" stroke-width="${1*i}"/>
            <circle cx="${t-d/2}" cy="${l}" r="${p}"
                    fill="#838bc5" stroke="#488fc2" stroke-width="${1*i}"/>
            <circle cx="${t+d/2}" cy="${l}" r="${p}"
                    fill="#838bc5" stroke="#488fc2" stroke-width="${1*i}"/>

            <path d="M${t-c/2},${o}
                     Q${t-.7*c},${o+18*i} ${t-.95*c-15*i},${o+12*i}"
                  fill="none" stroke="#488fc2" stroke-width="${1.5*i}" opacity="0.6"/>
            <path d="M${t+c/2},${o}
                     Q${t+.7*c},${o+18*i} ${t+.95*c+15*i},${o+12*i}"
                  fill="none" stroke="#488fc2" stroke-width="${1.5*i}" opacity="0.6"/>

            <path d="M${t-d/2},${l}
                     Q${t-.65*d},${l+14*i} ${t-.9*d-12*i},${l+9*i}"
                  fill="none" stroke="#488fc2" stroke-width="${1.2*i}" opacity="0.5"/>
            <path d="M${t+d/2},${l}
                     Q${t+.65*d},${l+14*i} ${t+.9*d+12*i},${l+9*i}"
                  fill="none" stroke="#488fc2" stroke-width="${1.2*i}" opacity="0.5"/>

            <path d="M${t-3*i},${l+8*i} L${t-5*i},${l+14*i}
                     L${t},${l+14*i} L${t},${l+20*i}
                     L${t+4*i},${l+11*i} L${t},${l+11*i} Z"
                  fill="#FCD170" opacity="0.6"/>
        `}_illustrationEV(t,e,s){const i=s/44,r=22*i,a=36*i,n=t-28*i,o=e-a/2,l=e+4*i,c=52*i,d=22*i,p=t+18*i-c/2,_=6*i;return j`
            <circle cx="${t}" cy="${e}" r="${s+4}" fill="none"
                    stroke="#8DC892" stroke-width="1.2" opacity="0.25"/>

            <rect x="${n}" y="${o}" width="${r}" height="${a}"
                  rx="${4*i}" fill="#1a2e22" stroke="#8DC892" stroke-width="${1.8*i}" opacity="0.95"/>
            <rect x="${n+3*i}" y="${o+4*i}" width="${r-6*i}" height="${10*i}"
                  rx="${2*i}" fill="#0a1a12" stroke="#8DC892" stroke-width="${.8*i}" opacity="0.8"/>
            <text x="${n+r/2}" y="${o+4*i+8*i}"
                  font-family="'Courier New',monospace" font-size="${5.5*i}"
                  fill="#8DC892" text-anchor="middle" opacity="0.8">AC</text>
            <path d="M${n+r/2-3*i},${o+18*i}
                     L${n+r/2-5*i},${o+25*i}
                     L${n+r/2},${o+25*i}
                     L${n+r/2},${o+32*i}
                     L${n+r/2+4*i},${o+22*i}
                     L${n+r/2},${o+22*i} Z"
                  fill="#FCD170" opacity="0.9"/>
            <circle cx="${n+r-5*i}" cy="${o+5*i}" r="${2.2*i}"
                    fill="#8DC892" opacity="0.9">
                <animate attributeName="opacity" values="0.9;0.3;0.9" dur="1.8s" repeatCount="indefinite"/>
            </circle>
            <path d="M${n+r},${o+.55*a}
                     C${n+r+10*i},${o+.55*a}
                       ${p-10*i},${l}
                       ${p},${l}"
                  fill="none" stroke="#8DC892" stroke-width="${2.5*i}"
                  stroke-linecap="round" opacity="0.7"/>
            <circle cx="${p}" cy="${l}" r="${3*i}"
                    fill="#8DC892" opacity="0.85"/>

            <rect x="${p+5*i}" y="${l}" width="${c-10*i}" height="${d/2}"
                  rx="${3*i}" fill="url(#carGrad)" stroke="#8DC892" stroke-width="${1.5*i}"/>
            <path d="M${p+12*i},${l}
                     L${p+10*i},${l-.7*d}
                     L${p+20*i},${l-.85*d}
                     L${p+c-18*i},${l-.85*d}
                     L${p+c-10*i},${l-.7*d}
                     L${p+c-8*i},${l} Z"
                  fill="url(#carGrad)" stroke="#8DC892" stroke-width="${1.5*i}"/>
            <path d="M${p+13*i},${l-2*i}
                     L${p+11*i},${l-.62*d}
                     L${p+22*i},${l-.78*d}
                     L${p+24*i},${l-2*i} Z"
                  fill="rgba(100,200,200,0.22)" stroke="rgba(100,200,200,0.4)" stroke-width="${.8*i}"/>
            <path d="M${p+c-14*i},${l-2*i}
                     L${p+c-22*i},${l-2*i}
                     L${p+c-20*i},${l-.78*d}
                     L${p+c-12*i},${l-.62*d} Z"
                  fill="rgba(100,200,200,0.22)" stroke="rgba(100,200,200,0.4)" stroke-width="${.8*i}"/>
            <circle cx="${p+14*i}" cy="${l+d/2-1*i}" r="${_}"
                    fill="#1a2525" stroke="#8DC892" stroke-width="${2*i}"/>
            <circle cx="${p+14*i}" cy="${l+d/2-1*i}" r="${.4*_}"
                    fill="#8DC892" opacity="0.5"/>
            <circle cx="${p+c-14*i}" cy="${l+d/2-1*i}" r="${_}"
                    fill="#1a2525" stroke="#8DC892" stroke-width="${2*i}"/>
            <circle cx="${p+c-14*i}" cy="${l+d/2-1*i}" r="${.4*_}"
                    fill="#8DC892" opacity="0.5"/>
            <ellipse cx="${p+c-7*i}" cy="${l+d/2-6*i}"
                     rx="${4*i}" ry="${2.5*i}"
                     fill="#FFF9C4" opacity="0.6"/>
        `}_renderFlow(t,e,s,i,r){const a=s.toFixed(1),n=String(t?28:-28),o=t?{kp:"1;0",kt:"0;1"}:null,l=[];for(let t=0;t<r;t++){const n=`-${(t/r*s).toFixed(2)}s`;l.push(j`
                <circle r="5" fill="${e}" opacity="0.12">
                    <animateMotion path="${i}" dur="${a}s" repeatCount="indefinite" calcMode="paced"
                                   keyPoints=${o?o.kp:K}
                                   keyTimes=${o?o.kt:K}
                                   begin="${n}"/>
                </circle>
                <circle r="2.5" fill="${e}" opacity="0.95">
                    <animateMotion path="${i}" dur="${a}s" repeatCount="indefinite" calcMode="paced"
                                   keyPoints=${o?o.kp:K}
                                   keyTimes=${o?o.kt:K}
                                   begin="${n}"/>
                </circle>
                <circle r="1" fill="rgba(255,255,255,0.9)" opacity="0.85">
                    <animateMotion path="${i}" dur="${a}s" repeatCount="indefinite" calcMode="paced"
                                   keyPoints=${o?o.kp:K}
                                   keyTimes=${o?o.kt:K}
                                   begin="${n}"/>
                </circle>
            `)}return j`
            <path d="${i}" fill="none" stroke="${e}" stroke-width="5"
                  stroke-dasharray="8,${20}" opacity="0.2" stroke-linecap="round">
                <animate attributeName="stroke-dashoffset" from="0" to="${n}"
                         dur="${a}s" repeatCount="indefinite"/>
            </path>
            <path d="${i}" fill="none" stroke="rgba(255,255,255,0.5)" stroke-width="1.2"
                  stroke-dasharray="6,${22}" opacity="0.45" stroke-linecap="round">
                <animate attributeName="stroke-dashoffset" from="0" to="${n}"
                         dur="${a}s" repeatCount="indefinite"/>
            </path>
            <path d="${i}" fill="none" stroke="${e}" stroke-width="2.5"
                  stroke-dasharray="8,${20}" opacity="0.65" stroke-linecap="round">
                <animate attributeName="stroke-dashoffset" from="0" to="${n}"
                         dur="${a}s" repeatCount="indefinite"/>
            </path>
            ${l}
        `}_sparkWavePath(t){const e=this._sunPtX,s=this._sunPtY,i=t.S.cx-e,r=t.S.cy-t.S.r-s,a=Math.sqrt(i*i+r*r),n=Math.max(2,Math.round(a/30)),o=this._val("solar_power",0),l=6+Math.min(8,o/1e3),c=Math.atan2(r,i),d=-Math.sin(c),p=Math.cos(c),_=8*n;let h=`M${e.toFixed(1)},${s.toFixed(1)}`;for(let t=1;t<=_;t++){const a=t/_,o=e+i*a,c=s+r*a,u=Math.sin(a*n*Math.PI*2)*l;h+=` L${(o+d*u).toFixed(1)},${(c+p*u).toFixed(1)}`}return this._sparkWaveD=h,j`<path id="spark-wave" d="${h}" fill="none"
                         stroke="rgba(255,200,60,0.12)" stroke-width="2.5" stroke-linecap="round"
                         filter="url(#glowSun)"/>`}_renderSunSpark(t){const e=12-7*Math.min(1,t/1e4),s=3+Math.floor(Math.min(3,t/3e3)),i=`${e.toFixed(0)}:${s}`;if(this._sunSparkSig!==i){this._sunSparkSig=i,this._sunSparkProps=[];for(let t=0;t<s;t++)this._sunSparkProps.push({kind:t%2==0?"gold":"white",r:1.5+2*Math.random(),opacity:.4+.5*Math.random(),dur:e*(.7+.6*Math.random()),delay:Math.random()*e})}const r=this._sparkWaveD;return this._sunSparkProps.map(t=>"gold"===t.kind?j`
            <circle r="${t.r.toFixed(1)}" fill="rgba(255,220,60,${t.opacity.toFixed(2)})" filter="url(#glowSun)">
                <animateMotion path="${r}" dur="${t.dur.toFixed(1)}s" repeatCount="indefinite" calcMode="paced"
                               begin="-${t.delay.toFixed(1)}s"/>
            </circle>
        `:j`
            <circle r="${(.6*t.r).toFixed(1)}" fill="rgba(255,255,230,${t.opacity.toFixed(2)})">
                <animateMotion path="${r}" dur="${t.dur.toFixed(1)}s" repeatCount="indefinite" calcMode="paced"
                               begin="-${t.delay.toFixed(1)}s"/>
            </circle>
        `)}_collectDevices(){const t=this._eid("controllable_devices_count"),e=t?this._hass?.states[t]:void 0;return e?.attributes?.devices?Object.entries(e.attributes.devices).filter(([,t])=>"ev_charger"!==t.device_type&&"battery"!==t.device_type).map(([t,e])=>{const s=e.power_entity?this._hass.states[e.power_entity]:null,i=s?At(s):e.current_power||0;return{id:t,...e,power:i,name:this._localizedDeviceName(t,e)}}).sort((t,e)=>e.power-t.power).slice(0,3):[]}_localizedDeviceName(t,e){const s={heat_pump:"device_heat_pump",hot_water:"device_hot_water"},i={heat_pump:"Heat Pump",hot_water:"Hot Water"}[t];if(i&&(e.name||"").trim()===i){const e=this._t(s[t]);if(e)return e}return e.name||t}_renderDeviceChips(){const t=this._collectDevices();return t.length?H`
            <div style="display:flex;gap:8px;padding:0 14px 14px;">
                ${t.map((t,e)=>{const s=ht,i=t.is_on||t.power>5;let r=t.name||t.id;return r.length>14&&(r=r.substring(0,13)+"…"),H`
                        <div class="${t.power_entity?"clickable":""}"
                             @click=${()=>t.power_entity&&this._fireMoreInfo(t.power_entity)}
                             style="flex:1;display:flex;flex-direction:column;align-items:center;gap:1px;
                                    padding:7px 4px;border-radius:12px;
                                    border:1px solid ${s}${i?"":"55"};
                                    background:rgba(128,128,128,${i?.07:.03});">
                            <svg viewBox="-16 -16 32 32" width="22" height="22" style="opacity:${i?1:.55}">
                                <g stroke="${s}" fill="none" stroke-width="1.6"
                                   stroke-linecap="round" stroke-linejoin="round">
                                    ${this._deviceIcon(t.device_type,t.name||t.id)}
                                </g>
                            </svg>
                            <div style="font-size:10px;color:${s};font-weight:600;opacity:${i?1:.85};
                                        white-space:nowrap;overflow:hidden;max-width:100%">${r}</div>
                            <div style="font-size:11px;color:${s};font-weight:800;opacity:${i?1:.85}">
                                ${i?ut(t.power):this._t("off")}</div>
                        </div>`})}
            </div>`:K}_renderDeviceStrip(t){const e=this._collectDevices();if(!e.length)return K;const s="'Segoe UI','Roboto',sans-serif";return e.map((e,i)=>{let r=(e.name||e.id).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");r.length>22&&(r=r.substring(0,21)+"…");const a=ht,n=e.is_on||e.power>5,o=310+50*i,l=540,c=`M${t.cx+t.r},${t.cy+10+8*i} C${t.cx+t.r+40},${t.cy+30+15*i} 510,${o-10} 524,${o}`,d=e.power>5?j`
                <circle r="1.5" fill="${a}" opacity="0.8">
                    <animateMotion path="${c}" dur="${mt(e.power).toFixed(1)}s" repeatCount="indefinite" calcMode="paced"/>
                </circle>
            `:K;return j`
                <path d="${c}" fill="none" stroke="${a}" stroke-width="1"
                      stroke-dasharray="3,5" opacity="${n?.3:.1}"/>
                ${d}
                <circle cx="${l}" cy="${o}" r="${14}" fill="rgba(128,128,128,${n?.06:.02})"
                        stroke="${a}" stroke-width="0.8" opacity="${n?.7:.3}"/>
                <g transform="translate(${l},${o}) scale(0.7)" stroke="${a}" fill="none"
                   opacity="${n?.6:.25}" stroke-width="1.3" stroke-linecap="round">
                    ${this._deviceIcon(e.device_type,e.name||e.id)}
                </g>
                <text x="${560}" y="${o-2}" font-family="${s}" font-size="10"
                      font-weight="500" fill="${a}" opacity="0.85">${r}</text>
                <text x="${560}" y="${o+11}" font-family="${s}" font-size="10"
                      font-weight="700" fill="${a}" opacity="${n?.95:.75}">${ut(e.power)}</text>
            `})}_glowFilter(t,e,s){return j`<filter id="${t}" x="-35%" y="-35%" width="170%" height="170%">
            <feGaussianBlur stdDeviation="${s}" result="blur"/>
            <feFlood flood-color="${e}" flood-opacity="0.28"/>
            <feComposite in2="blur" operator="in"/>
            <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>`}_showMoreInfo(t){const e=this._eid(t);e&&this.dispatchEvent(new CustomEvent("hass-more-info",{bubbles:!0,composed:!0,detail:{entityId:e}}))}_getLayout(){return this._compact?{vb:"0 0 400 680",S:{cx:200,cy:100,r:44,labelY:154},I:{cx:200,cy:232,r:20},B:{cx:100,cy:360,r:44,labelY:414},G:{cx:300,cy:360,r:44,labelY:414},H:{cx:200,cy:540,r:48,labelY:598},E:{cx:84,cy:555,r:34,labelY:598},paths:{solar:"M200,144 L200,212",battery:"M188,242 C155,278 120,315 100,316",grid:"M212,242 C245,278 280,315 300,316",home:"M200,252 C200,390 200,460 200,492",ev:"M200,252 C200,400 140,490 84,521"},sunArc:"M30,68 Q200,6 370,68",sunX:200,sunY:20,sunR:12,sunRisingX:40,sunSettingX:360,sunLabelY:76,starX:[60,120,280,330,180],starY:[20,12,18,24,8],font:{label:11,value:15,sub:10},statusY:660,wmX:390,wmY:676}:{vb:"0 0 700 510",S:{cx:85,cy:140,r:48,labelY:200},I:{cx:220,cy:200,r:20},E:{cx:150,cy:390,r:42,labelY:442},B:{cx:340,cy:390,r:48,labelY:448},H:{cx:400,cy:230,r:52,labelY:292},G:{cx:570,cy:140,r:46,labelY:198},paths:{solar:"M118,148 C158,165 192,188 208,200",home:"M242,198 C300,200 350,210 360,218",battery:"M228,215 C260,280 320,340 338,342",grid:"M232,188 C320,130 450,110 524,130",ev:"M210,215 C180,275 162,330 150,348"},sunArc:"M20,52 Q330,2 640,52",sunX:330,sunY:12,sunR:12,sunRisingX:28,sunSettingX:632,sunLabelY:60,starX:[100,200,450,550,330],starY:[20,12,15,28,8],font:{label:11,value:16,sub:10},statusY:495,wmX:690,wmY:506}}_deviceIcon(t,e){const s=(e||"").toLowerCase();return"ev_charger"===(t||"").toLowerCase()||s.includes("keba")||s.includes("charger")||s.includes("wallbox")?j`<rect x="-5" y="-9" width="10" height="14" rx="2"/>
                       <path d="M-1.5,-3.5 L0,1.5 L1.5,-3.5"/>
                       <line x1="0" y1="5" x2="0" y2="9"/>`:s.includes("heiz")||s.includes("heat")||s.includes("warm")||s.includes("boiler")?j`<path d="M-3,-9 C-3,-3 3,-3 3,-9"/>
                       <path d="M-3,-2 C-3,4 3,4 3,-2"/>
                       <path d="M-3,5 C-3,9 3,9 3,5"/>`:s.includes("wash")||s.includes("spül")||s.includes("geschirr")||s.includes("wasch")?j`<circle r="9"/><circle r="4.5"/><circle r="1.3" fill="currentColor" opacity="0.3" stroke="none"/>`:s.includes("pool")||s.includes("pump")?j`<circle r="7"/><path d="M-5,0 L5,0 M0,-5 L0,5" opacity="0.5"/>`:s.includes("klima")||s.includes("ac")||s.includes("cool")||s.includes("air")?j`<rect x="-9" y="-5" width="18" height="10" rx="2"/>
                       <path d="M-5,5 C-5,9 -2,9 -2,5" fill="none"/>
                       <path d="M2,5 C2,9 5,9 5,5" fill="none"/>`:s.includes("light")||s.includes("licht")||s.includes("lamp")?j`<path d="M-4,-9 C-7,-2 -2,3 -1.5,5 L1.5,5 C2,3 7,-2 4,-9 C2,-12 -2,-12 -4,-9Z"/>
                       <line x1="-1.5" y1="6" x2="1.5" y2="6"/>`:j`<path d="M-2.5,-9 L-2.5,0 L-5,0 L0,9 L0,0 L2.5,0 L-2.5,-9Z"/>`}getCardSize(){return 7}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"sem-system-diagram-card",name:"SEM System Diagram",description:"Power flow visualization with inline SVG illustrations for each energy component",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-system-diagram-card"});const nr=["/local/custom_components/solar_energy_management/dashboard/card/vendor/chart.umd.min.js","https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"],or=["/local/custom_components/solar_energy_management/dashboard/card/vendor/chartjs-adapter-date-fns.bundle.min.js","https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"];function lr(t,e,s){if(!t.length)return void s(new Error("all sources failed"));const i=document.createElement("script");i.src=t[0],i.onload=()=>e(),i.onerror=()=>lr(t.slice(1),e,s),document.head.appendChild(i)}let cr=null;const dr=pt||{solar:"#ff9800",gridImport:"#488fc2",gridExport:"#8353d1",batteryOut:"#4db6ac",home:"#5BC8D8",ev:"#8DC892"},pr={costs:{title:"energy_costs",y_label:"_currency_",stacked:!1,daily:[{suffix:"daily_costs",name:"Import",color:dr.gridImport,type:"bar",negate:!0},{suffix:"daily_export_revenue",name:"export",color:dr.gridExport,type:"bar"},{suffix:"daily_net_cost",name:"net",color:dr.solar,type:"line",negate:!0}],monthly:[{suffix:"monthly_costs",name:"Import",color:dr.gridImport,type:"bar",negate:!0},{suffix:"monthly_export_revenue",name:"export",color:dr.gridExport,type:"bar"},{suffix:"monthly_net_cost",name:"net",color:dr.solar,type:"line",negate:!0}]},savings:{title:"energy_savings",y_label:"_currency_",stacked:!0,daily:[{suffix:"daily_savings",name:"solar_savings",color:dr.solar,type:"area"},{suffix:"daily_battery_savings",name:"battery_savings",color:dr.batteryOut,type:"area"}],monthly:[{suffix:"monthly_savings",name:"solar_savings",color:dr.solar,type:"area"},{suffix:"monthly_battery_savings",name:"battery_savings",color:dr.batteryOut,type:"area"}]},energy:{title:"energy_balance",y_label:"kWh",stacked:!1,defaultPeriod:"7d",daily:[{suffix:"daily_solar_energy",name:"solar",color:dr.solar,type:"bar"},{suffix:"daily_home_energy",name:"home",color:dr.home,type:"bar"},{suffix:"daily_grid_import_energy",name:"grid_import",color:dr.gridImport,type:"bar"},{suffix:"daily_grid_export_energy",name:"grid_export",color:dr.gridExport,type:"bar"}],monthly:[{suffix:"monthly_solar_energy",name:"solar",color:dr.solar,type:"bar"},{suffix:"monthly_home_energy",name:"home",color:dr.home,type:"bar"},{suffix:"monthly_grid_import_energy",name:"grid_import",color:dr.gridImport,type:"bar"},{suffix:"monthly_grid_export_energy",name:"grid_export",color:dr.gridExport,type:"bar"}]},power:{title:"power_flow",y_label:"W",stacked:!1,hourly:[{suffix:"solar_power",name:"solar",color:dr.solar,type:"area"},{suffix:"home_consumption_power",name:"home",color:dr.home,type:"area"},{suffix:"grid_power",name:"grid",color:dr.gridImport,type:"area"}]},forecast:{title:"Forecast vs Actual",y_label:"W",stacked:!1,hourly:[{suffix:"forecast_power_now_w",name:"forecast",color:dr.solar,type:"area"},{suffix:"solar_power",name:"actual",color:dr.batteryOut,type:"line"}]},battery:{title:"battery",y_label:"W",y2_label:"%",stacked:!1,hourly:[{suffix:"battery_power",name:"power",color:dr.batteryOut,type:"area"},{suffix:"battery_soc",name:"soc",color:"#ff9800",type:"line",y_axis:1}]},ev:{title:"ev_charging",y_label:"W",stacked:!0,defaultPeriod:"today",y_min:0,y_suggested_max:2e3,hourly:[{suffix:"flow_solar_to_ev_power",name:"solar",color:dr.solar,type:"area"},{suffix:"flow_battery_to_ev_power",name:"battery",color:dr.batteryOut,type:"area"},{suffix:"flow_grid_to_ev_power",name:"grid",color:dr.gridImport,type:"area"}],daily:[{suffix:"daily_ev_energy",name:"ev_energy",color:dr.ev,type:"bar"}],monthly:[{suffix:"monthly_ev_energy",name:"ev_energy",color:dr.ev,type:"bar"}]}};kt("sem-chart-card",class extends Lt{constructor(){super(),this._chart=null,this._period=null,this._fetchTimer=null,this._cachedChartTheme=null,this._boundPeriodHandler=t=>this._onPeriodChange(t.detail),this._prefix="sensor.sem_",this._preset=null,this._emptyMsg="",this._fetchSeq=0}setConfig(t){if(!t.preset&&!t.series)throw new Error("sem-chart-card requires either preset or series config");this._config=t,this._prefix=t.entity_prefix||"sensor.sem_",this._preset=t.preset?pr[t.preset]:null,this.requestUpdate()}set hass(t){this._hass=t;const e=t?.language;if(e!==this._lang)return this._lang=e,void this.requestUpdate();this._period||this._setDefaultPeriod()}get hass(){return this._hass}connectedCallback(){super.connectedCallback(),document.addEventListener("sem-period-change",this._boundPeriodHandler),this._rollInterval=setInterval(()=>this._rollRelativePeriod(),3e5),this._boundVisibility=()=>{document.hidden||this._rollRelativePeriod()},document.addEventListener("visibilitychange",this._boundVisibility),this._period&&this._redraw()}disconnectedCallback(){super.disconnectedCallback(),document.removeEventListener("sem-period-change",this._boundPeriodHandler),this._boundVisibility&&document.removeEventListener("visibilitychange",this._boundVisibility),clearInterval(this._rollInterval),this._chart&&(this._chart.destroy(),this._chart=null),clearTimeout(this._fetchTimer),this._fetchSeq++}_redraw(){this._period&&(this._period.key===this._defaultKey()?this._setDefaultPeriod():this._onPeriodChange(this._period))}_rollRelativePeriod(){this._period&&this._hass&&this._period.key===this._defaultKey()&&this._setDefaultPeriod()}firstUpdated(){this._period||this._setDefaultPeriod()}static get styles(){return[Ot,a`
            :host { display: block; }
            .sem-chart-wrap {
                padding: 16px;
                min-height: 280px;
                position: relative;
            }
            .chart-header { margin-bottom: 12px; }
            .chart-title {
                font-size: 15px; font-weight: 600;
                color: var(--primary-text-color, #e0e0e0);
                font-family: 'Segoe UI','Roboto',sans-serif;
                letter-spacing: 0.3px;
                font-variant-numeric: tabular-nums;
            }
            .chart-subtitle {
                font-size: 12px;
                color: var(--secondary-text-color, #757575);
                margin-top: 2px;
                font-family: 'Segoe UI','Roboto',sans-serif;
                font-variant-numeric: tabular-nums;
            }
            .chart-container {
                position: relative;
                height: 250px;
                filter: drop-shadow(0 0 1px rgba(200,220,240,0.10));
            }
            canvas { width: 100% !important; height: 100% !important; }
            .empty-msg {
                position: absolute;
                inset: 0;
                display: none;
                align-items: center;
                justify-content: center;
                color: var(--secondary-text-color, #616161);
                font-size: 13px;
                font-family: 'Segoe UI','Roboto',sans-serif;
            }
            .empty-msg.visible { display: flex; }
        `]}render(){const t=this._preset||{},e=this._config?.title?this._t(this._config.title):this._t(t.title||"SEM Chart"),s=this._period?.labelKey?this._t(this._period.labelKey):"";return H`
            <ha-card>
                <div class="sem-chart-wrap">
                    <div class="chart-header">
                        <div class="chart-title">${e}</div>
                        <div class="chart-subtitle">${s}</div>
                    </div>
                    <div class="chart-container">
                        <canvas style="display:${this._emptyMsg?"none":"block"}"></canvas>
                        <div class="empty-msg ${this._emptyMsg?"visible":""}">${this._emptyMsg}</div>
                    </div>
                </div>
            </ha-card>
        `}_startOfDayInHaTz(t){return function(t,e){if(!e)return new Date(t.getFullYear(),t.getMonth(),t.getDate());try{const s=new Intl.DateTimeFormat("en-US",{timeZone:e,year:"numeric",month:"2-digit",day:"2-digit"}),i=Object.fromEntries(s.formatToParts(t).map(t=>[t.type,t.value])),r=new Date(Number(i.year),Number(i.month)-1,Number(i.day),0,0,0,0),a=new Intl.DateTimeFormat("en-US",{timeZone:e,hour:"2-digit",minute:"2-digit",hour12:!1}).formatToParts(r),n=Number(a.find(t=>"hour"===t.type).value),o=Number(a.find(t=>"minute"===t.type).value),l=(60*n+o)%1440,c=0===l?0:l<=720?-l:1440-l;return new Date(r.getTime()+60*c*1e3)}catch(e){return new Date(t.getFullYear(),t.getMonth(),t.getDate())}}(t,this._hass?.config?.time_zone)}_defaultKey(){const t=this._preset,e=this._config?.default_period||t&&t.defaultPeriod;return t&&("today"===e||"24h"===e||t.hourly&&!t.daily)?"today"===e?"today":"24h":"7d"===e?"7d":"week"}_setDefaultPeriod(){const t=new Date,e=this._defaultKey();if("today"===e||"24h"===e){const s="today"===e,i=s?this._startOfDayInHaTz(t):new Date(t.getTime()-864e5),r=s?"period_today":"last_24h";this._onPeriodChange({start:i,end:t,granularity:"hour",labelKey:r,key:e})}else if("7d"===e){const e=this._startOfDayInHaTz(t);e.setDate(e.getDate()-6),this._onPeriodChange({start:e,end:t,granularity:"day",labelKey:"last_7_days",key:"7d"})}else{const e=t.getDay()||7,s=this._startOfDayInHaTz(t);s.setDate(s.getDate()-(e-1)),this._onPeriodChange({start:s,end:t,granularity:"day",labelKey:"period_this_week",key:"week"})}}_onPeriodChange(t){this._period={...t,labelKey:t.labelKey||{today:"period_today",yesterday:"period_yesterday",week:"period_this_week",month:"period_this_month",year:"period_this_year","24h":"last_24h","7d":"last_7_days"}[t.key]},this.requestUpdate(),clearTimeout(this._fetchTimer),this._fetchTimer=setTimeout(()=>this._fetchAndRender(),150)}_resolveSeries(){if(this._config?.series)return this._config.series.map(t=>({entity:t.entity,name:t.name||t.entity,color:t.color||"#42A5F5",type:t.type||"bar",y_axis:t.y_axis||0}));const t=this._preset;if(!t)return[];const e=this._period?.granularity||"day";if(this._config?.per_charger&&"ev"===this._config?.preset&&"hour"===e)return this._discoverPerChargerSeries();const s="hour"===e&&t.hourly?t.hourly:"month"===e&&t.monthly?t.monthly:t.daily||t.hourly||[],i=s===t.daily||s===t.monthly;return s.map(t=>({entity:`${this._prefix}${t.suffix}`,name:this._t(t.name),color:t.color,type:t.type,y_axis:t.y_axis||0,negate:t.negate||!1,cumulative:i}))}_discoverPerChargerSeries(){const t=this._hass?.states||{},e=["#8DC892","#64B5F6","#FFB74D","#BA68C8","#4DB6AC","#F06292","#A1887F","#7986CB"],s=/^sensor\.sem_charger_(.+)_power$/,i=[];for(const e of Object.keys(t)){const r=e.match(s);if(!r)continue;const a=r[1],n=t[e]?.attributes?.charger_name||t[e]?.attributes?.friendly_name?.replace(/^SEM\s+/i,"").replace(/\s+Power$/i,"")||a.replace(/_/g," ");i.push({id:a,eid:e,friendly:n})}return i.sort((t,e)=>t.id.localeCompare(e.id)),i.map((t,s)=>({entity:t.eid,name:t.friendly,color:e[s%e.length],type:"area",y_axis:0}))}async _fetchAndRender(){if(!this._hass||!this._period||!this.isConnected)return;const t=this._resolveSeries();if(!t.length)return;const{start:e,end:s,granularity:i}=this._period,r=++this._fetchSeq,a=()=>r!==this._fetchSeq||!this.isConnected;let n;try{n=await this._fetchStatistics(t,e.toISOString(),s.toISOString(),i)}catch(t){if(a())return;return console.debug("sem-chart-card: fetch error",t),void this._showEmpty(this._t("data_unavailable"))}a()||(n&&!n.every(t=>!t.data.length)?(this._hideEmpty(),await this.updateComplete,a()||await this._renderChart(n,t,a)):this._showEmpty(this._t("no_data_for_period")))}async _fetchStatistics(t,e,s,i){const r=t.map(t=>t.entity),a="month"===i?"month":"hour"===i?"hour":"day",n={power:"W",energy:"kWh"};let o;try{o=await this._hass.callWS({type:"recorder/statistics_during_period",start_time:e,end_time:s,statistic_ids:r,period:a,types:["state","mean","max"],units:n})}catch{o=await this._hass.callWS({type:"history/statistics_during_period",start_time:e,end_time:s,statistic_ids:r,period:a,units:n})}const l=(this._config?.stacked??this._preset?.stacked??!1)&&"hour"===a;return t.map(t=>({data:(o[t.entity]||[]).map(e=>{let s=l?e.mean??e.state??0:e.max??e.state??e.mean??0;return t.negate&&(s=-s),{x:new Date(e.start),y:s}})}))}async _renderChart(t,e,s=()=>!1){const i=await(cr||(cr=new Promise((t,e)=>{const s=()=>lr(or,()=>t(window.Chart),()=>t(window.Chart));if(window.Chart)return(()=>{try{return new window.Chart._adapters._date({}).formats(),!0}catch{return!1}})()?void t(window.Chart):void s();lr(nr,s,()=>e(new Error("Failed to load Chart.js")))}),cr));if(s())return;const r=this.renderRoot.querySelector("canvas");if(!r)return;const a=this._theme(),n=this._preset||{},o=this._config?.stacked??n.stacked??!1;let l=this._config?.y_label||n.y_label||"";"_currency_"===l&&(l=ft(this._hass));const c=n.y2_label||"",d=e.some(t=>1===t.y_axis),p=this._period?.granularity||"day",_=r.getContext("2d"),h=e.map((e,s)=>{const i="area"===e.type,r="bar"===e.type;return{label:e.name,data:t[s].data,cumulative:!!e.cumulative,backgroundColor:r?e.color+"CC":i?e.color+"30":"transparent",borderColor:e.color,borderWidth:r?0:2,fill:!!i&&(o&&s>0?"-1":"origin"),type:r?"bar":"line",tension:.4,pointRadius:0,pointHitRadius:10,pointHoverRadius:4,pointHoverBorderWidth:2,pointHoverBackgroundColor:e.color,pointHoverBorderColor:"#fff",yAxisID:1===e.y_axis?"y1":"y",order:r?2:1,borderRadius:r?4:0,barPercentage:.7}}),u="hour"===p?"hour":"month"===p?"month":"day",g={id:"crosshair",afterDraw(t){if(t.tooltip?._active?.length){const e=t.tooltip._active[0].element.x,s=t.scales.y,i=t.ctx;i.save(),i.beginPath(),i.moveTo(e,s.top),i.lineTo(e,s.bottom),i.lineWidth=1,i.strokeStyle="rgba(255,255,255,0.15)",i.stroke(),i.restore()}}},m={type:"bar",data:{datasets:h},plugins:[g,{id:"gradientFill",beforeDatasetsDraw(t){const s=t.ctx;t.data.datasets.forEach((i,r)=>{if("area"!==e[r]?.type)return;if(t.getDatasetMeta(r).hidden)return;const a=t.scales[i.yAxisID||"y"];if(!a)return;const n=s.createLinearGradient(0,a.top,0,a.bottom);n.addColorStop(0,i.borderColor+"60"),n.addColorStop(.6,i.borderColor+"18"),n.addColorStop(1,i.borderColor+"02"),i.backgroundColor=n})}}],options:{responsive:!0,maintainAspectRatio:!1,animation:{duration:300,easing:"easeOutQuart"},interaction:{mode:"index",intersect:!1},plugins:{legend:{display:!0,position:"bottom",labels:{color:a.textSec||"#9e9e9e",font:{size:11,weight:"500",family:"'Segoe UI','Roboto',sans-serif"},boxWidth:12,boxHeight:12,borderRadius:3,useBorderRadius:!0,padding:14,generateLabels:t=>function(t,e,s){return t.map(t=>{const i=e[t.datasetIndex];if(!i)return t;const r=i.cumulative?i.data.reduce((t,e)=>t+(e?.y??0),0):i.data[i.data.length-1]?.y??0,a="y1"===i.yAxisID?"%":s||"",n=Math.abs(r),o=n>=1e3?(r/1e3).toFixed(1)+"k":n<10?r.toFixed(1):r.toFixed(0);return t.text=`${t.text}: ${o} ${a}`,t})}(i.defaults.plugins.legend.labels.generateLabels(t),t.data.datasets,l)}},tooltip:{backgroundColor:a.tooltipBg||"rgba(15,18,25,0.94)",titleColor:a.tooltipText||"#e0e0e0",titleFont:{family:"'Segoe UI','Roboto',sans-serif",weight:"600",size:12},bodyColor:a.textSec||"#b0b0b0",bodyFont:{family:"'Segoe UI','Roboto',sans-serif",size:11},borderColor:a.tooltipBorder||"rgba(255,255,255,0.08)",borderWidth:1,cornerRadius:10,padding:{top:10,bottom:10,left:14,right:14},bodySpacing:6,displayColors:!0,boxPadding:4,callbacks:{title:t=>{if(!t||!t.length)return"";const e=new Date(t[0].parsed.x);if(isNaN(e))return"";const s=this._hass?.language||"en",i=this._hass?.config?.time_zone||void 0;try{return"hour"===p?e.toLocaleTimeString(s,{hour:"2-digit",minute:"2-digit",timeZone:i}):"month"===p?e.toLocaleDateString(s,{month:"short",year:"numeric",timeZone:i}):e.toLocaleDateString(s,{day:"numeric",month:"short",timeZone:i})}catch(t){return"hour"===p?e.toLocaleTimeString(s):e.toLocaleDateString(s)}},label:t=>{const e=t.parsed.y,s="y1"===t.dataset.yAxisID?"%":l,i=Math.abs(e),r=i>=1e3?(e/1e3).toFixed(1)+"k":i<10?e.toFixed(2):e.toFixed(1);return` ${t.dataset.label}: ${r} ${s}`}}}},scales:{x:{type:"time",min:this._period.start.toISOString(),max:this._period.end.toISOString(),time:{unit:u,tooltipFormat:"hour"===p?"HH:mm":"month"===p?"MMM yyyy":"dd MMM",displayFormats:{hour:"HH:mm",day:"dd MMM",month:"MMM"}},grid:{color:"rgba(255,255,255,0.02)",drawBorder:!1,drawTicks:!1},ticks:{color:a.textSec||"#757575",font:{size:10,family:"'Segoe UI','Roboto',sans-serif"},maxRotation:0,padding:6,callback:(t,e,s)=>{const i=s[e];if(!i)return t;const r=new Date(i.value);if(isNaN(r))return t;const a=this._hass?.language||"en",n=this._hass?.config?.time_zone||void 0;try{return"hour"===u?r.toLocaleTimeString(a,{hour:"2-digit",minute:"2-digit",timeZone:n}):"month"===u?r.toLocaleDateString(a,{month:"short",timeZone:n}):r.toLocaleDateString(a,{day:"numeric",month:"short",timeZone:n})}catch(t){return"hour"===u?r.toLocaleTimeString(a,{hour:"2-digit",minute:"2-digit"}):r.toLocaleDateString(a,{day:"numeric",month:"short"})}}},stacked:o},y:{position:"left",grid:{color:"rgba(255,255,255,0.04)",drawBorder:!1,drawTicks:!1},ticks:{color:a.textSec||"#757575",font:{size:10,family:"'Segoe UI','Roboto',sans-serif"},padding:8,callback:t=>{const e=Math.abs(t);return e>=1e3?(t/1e3).toFixed(1)+"k":e<.01&&e>0?"":t%1==0?t:t.toFixed(1)}},title:{display:!!l,text:l,color:a.textSec||"#757575",font:{size:11,family:"'Segoe UI','Roboto',sans-serif"}},stacked:o,beginAtZero:"W"!==l||0===this._preset?.y_min,...null!=this._preset?.y_min?{min:this._preset.y_min}:{},...null!=this._preset?.y_suggested_max?{suggestedMax:this._preset.y_suggested_max}:{}}}}};d&&(m.options.scales.y1={position:"right",grid:{drawOnChartArea:!1,drawTicks:!1},ticks:{color:"#ff9800",font:{size:10},padding:8,callback:t=>t+"%"},title:{display:!!c,text:c,color:"#ff9800",font:{size:11}},min:0,max:100}),this._chart&&(this._chart.destroy(),this._chart=null),this._chart=new i(_,m)}_showEmpty(t){this._emptyMsg=t,this.requestUpdate()}_hideEmpty(){this._emptyMsg&&(this._emptyMsg="",this.requestUpdate())}getCardSize(){return 5}static getStubConfig(){return{preset:"costs"}}},{type:"sem-chart-card",name:"SEM Chart",description:"Period-reactive chart with glassmorphism styling and built-in presets",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-chart-card"});const{I:_r}=nt,hr=t=>t,ur=()=>document.createComment(""),gr=(t,e,s)=>{const i=t._$AA.parentNode,r=void 0===e?t._$AB:e._$AA;if(void 0===s){const e=i.insertBefore(ur(),r),a=i.insertBefore(ur(),r);s=new _r(e,a,t,t.options)}else{const e=s._$AB.nextSibling,a=s._$AM,n=a!==t;if(n){let e;s._$AQ?.(t),s._$AM=t,void 0!==s._$AP&&(e=t._$AU)!==a._$AU&&s._$AP(e)}if(e!==r||n){let t=s._$AA;for(;t!==e;){const e=hr(t).nextSibling;hr(i).insertBefore(t,r),t=e}}}return s},mr=(t,e,s=t)=>(t._$AI(e,s),t),fr={},yr=(t,e=fr)=>t._$AH=e,vr=t=>{t._$AR(),t._$AA.remove()},br=(t,e,s)=>{const i=new Map;for(let r=e;r<=s;r++)i.set(t[r],r);return i},xr=Gi(class extends Ki{constructor(t){if(super(t),t.type!==ji)throw Error("repeat() can only be used in text expressions")}dt(t,e,s){let i;void 0===s?s=e:void 0!==e&&(i=e);const r=[],a=[];let n=0;for(const e of t)r[n]=i?i(e,n):n,a[n]=s(e,n),n++;return{values:a,keys:r}}render(t,e,s){return this.dt(t,e,s).values}update(t,[e,s,i]){const r=(t=>t._$AH)(t),{values:a,keys:n}=this.dt(e,s,i);if(!Array.isArray(r))return this.ut=n,a;const o=this.ut??=[],l=[];let c,d,p=0,_=r.length-1,h=0,u=a.length-1;for(;p<=_&&h<=u;)if(null===r[p])p++;else if(null===r[_])_--;else if(o[p]===n[h])l[h]=mr(r[p],a[h]),p++,h++;else if(o[_]===n[u])l[u]=mr(r[_],a[u]),_--,u--;else if(o[p]===n[u])l[u]=mr(r[p],a[u]),gr(t,l[u+1],r[p]),p++,u--;else if(o[_]===n[h])l[h]=mr(r[_],a[h]),gr(t,r[p],r[_]),_--,h++;else if(void 0===c&&(c=br(n,h,u),d=br(o,p,_)),c.has(o[p]))if(c.has(o[_])){const e=d.get(n[h]),s=void 0!==e?r[e]:null;if(null===s){const e=gr(t,r[p]);mr(e,a[h]),l[h]=e}else l[h]=mr(s,a[h]),gr(t,r[p],s),r[e]=null;h++}else vr(r[_]),_--;else vr(r[p]),p++;for(;h<=u;){const e=gr(t,l[u+1]);mr(e,a[h]),l[h++]=e}for(;p<=_;){const t=r[p++];null!==t&&vr(t)}return this.ut=n,yr(t,l),G}});function $r(t){const e=[],s=new Set,i=r=>{var a;s.has(r.id)||(e.push(r),s.add(r.id),(a=r.id,t.filter(t=>(t.dependsOn||[]).includes(a)&&!s.has(t.id))).forEach(i))};return t.filter(t=>!(t.dependsOn||[]).length).forEach(i),t.forEach(t=>{s.has(t.id)||e.push(t)}),e}const wr=["switch","current","input_boolean","service"],kr={switch:["switch"],current:["number","input_number"],input_boolean:["input_boolean"]};function Sr(t){return String(t??"").replace(/&/g,"&amp;").replace(/"/g,"&quot;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}const Cr="width:100%;padding:8px;margin:6px 0 12px;border-radius:6px;border:1px solid rgba(255,255,255,0.1);background:rgba(0,0,0,0.2);color:inherit;box-sizing:border-box";function zr(t,e){if(e.power_entity&&t){const e=At(t);return null==e?null:e/1e3}return(e.current_power||0)/1e3}const Mr="https://github.com/traktore-org/sem-community/blob/develop/docs/ENERGY_PLANNER.md#comfort-banking",Dr=["controllable_devices_count","consecutive_peak_15min","load_management_status","target_peak_limit","grid_power"];kt("sem-load-priority-card",class extends Lt{constructor(){super(),this.devices=[],this.targetPeakLimit=null,this.peakLimitUnlimited=!1,this.currentPeak=null,this.gridImportKw=null,this.slotAllowedW=null,this.slotUsedKwh=null,this.loadManagementStatus="normal",this._sortable=null,this._interacting=!1,this._lastDeviceSig="",this._showHelp=!1,this._goalOpen={},this._goalDrag=null}setConfig(t){this._config=t,this._prefix=t.entity_prefix||"sensor.sem_",this.requestUpdate()}set hass(t){this._hass,this._hass=t;const e=t?.language;if(e!==this._lang)return this._lang=e,this._lastDeviceSig="",this._lastReads=this._readStates(t),this._updateDeviceData(),void this.requestUpdate();if(this._interacting)return;if(this._isFrozen())return;if(this._priorityFrozenUntil&&Date.now()<this._priorityFrozenUntil)return;const s=this._readStates(t);this._lastReads&&s.every((t,e)=>t===this._lastReads[e])||(this._lastReads=s,this._updateDeviceData(),this.requestUpdate())}_readStates(t){return Dr.map(e=>t?.states?.[`${this._prefix}${e}`])}get hass(){return this._hass}disconnectedCallback(){super.disconnectedCallback(),this._drag&&(window.removeEventListener("pointermove",this._dragMoveBound),window.removeEventListener("pointerup",this._dragEndBound),window.removeEventListener("pointercancel",this._dragEndBound),this._drag=null,this._interacting=!1)}async firstUpdated(){this._bindEvents(),this._ensureEntityPicker()}async updated(t){const e=this.devices.map(t=>t.id).join(",");e!==this._lastDeviceSig&&(this._lastDeviceSig=e,this._bindEvents())}static get styles(){return a`
            /* (#913 follow-up) a refused service call, in the modal's error voice */
            .svc-error { margin: 6px 0 8px; padding: 6px 10px; border-radius: 6px;
                         background: rgba(244, 67, 54, .12); color: #f44336;
                         font-size: 0.85em; }
            :host { display: block; }
            ha-card {
                overflow: visible;
                backdrop-filter: blur(18px) saturate(160%);
                -webkit-backdrop-filter: blur(18px) saturate(160%);
                border: 1px solid var(--divider-color, rgba(255,255,255,0.08));
                border-radius: 16px !important;
                box-shadow: var(--ha-card-box-shadow, 0 4px 24px rgba(0,0,0,0.35));
            }
            .card-content { padding: 14px 16px; font-family: 'Segoe UI','Roboto',sans-serif; color: var(--primary-text-color); }
            .status-bar { display:flex; align-items:center; gap:8px; margin-bottom:12px; padding-bottom:10px; border-bottom:1px solid var(--divider-color, rgba(128,128,128,0.12)); font-size:0.95em; }
            .status-text { text-transform:uppercase; letter-spacing:0.5px; font-weight:600; opacity:0.85; }
            .peak-dot { width:9px; height:9px; border-radius:50%; }
            .peak-box { background:var(--secondary-background-color, rgba(255,255,255,0.04)); border:1px solid var(--divider-color, rgba(255,255,255,0.08)); border-radius:12px; padding:12px; margin-bottom:10px; backdrop-filter: blur(8px); }
            .peak-row { display:flex; justify-content:space-between; margin-bottom:4px; font-size:1em; }
            .peak-row:last-of-type { margin-bottom:0; }
            .dim { opacity:0.55; font-size:1em; }
            .mono { font-variant-numeric:tabular-nums; font-weight:500; }
            .bar { width:100%; height:5px; background:var(--divider-color, rgba(128,128,128,0.12)); border-radius:3px; overflow:hidden; margin-top:8px; }
            .bar-fill { height:100%; border-radius:3px; transition:width 0.4s ease, background 0.4s ease; }
            .section-label { font-size:0.95em; opacity:0.55; margin-bottom:10px; display:flex; align-items:center; gap:6px; }
            .device-list { min-height:40px; }
            .device { display:flex; align-items:stretch; background:var(--secondary-background-color, rgba(255,255,255,0.04)); border:1px solid var(--divider-color, rgba(255,255,255,0.08)); border-radius:12px; margin-bottom:6px; transition:transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease; overflow:hidden; backdrop-filter:blur(8px); }
            /* Pointer-drag (Lit-native): the lifted row follows the finger,
               a bright line shows where it will drop. box-shadow is not
               clipped by the row's overflow, so the drop-line always shows. */
            .device.dragging-row { opacity:0.95; z-index:20; position:relative; border-color:#ff9800; box-shadow:0 10px 26px rgba(0,0,0,0.45); cursor:grabbing; }
            .device.drop-above { box-shadow:0 -3px 0 0 #ff9800; }
            .device.drop-below { box-shadow:0 3px 0 0 #ff9800; }
            .drag-handle { display:flex; align-items:center; justify-content:center; width:32px; min-width:32px; cursor:grab; font-size:16px; opacity:0.3; user-select:none; touch-action:none; border-right:1px solid var(--divider-color, rgba(128,128,128,0.12)); }
            .drag-handle:hover { opacity:0.6; }
            .drag-handle:active { cursor:grabbing; }
            .device-body { flex:1; padding:10px 12px; min-width:0; }
            .device-top { display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; }
            .device-name { display:flex; align-items:center; gap:6px; font-weight:500; font-size:0.95em; min-width:0; overflow:hidden; }
            .device-name span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
            .device-power { font-size:1em; font-weight:500; font-variant-numeric:tabular-nums; white-space:nowrap; opacity:0.7; }
            .device-bottom { display:flex; align-items:center; gap:8px; font-size:0.95em; flex-wrap:wrap; }
            .operator-lock {
                padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600;
                color: #ff9800; border: 1px solid #ff9800; background: rgba(255,152,0,.10);
                white-space: nowrap;
            }
            .status-dot.locked { background:#ff9800; }
            .status-dot { width:7px; height:7px; border-radius:50%; background:var(--divider-color, rgba(128,128,128,0.12)); flex-shrink:0; }
            .status-dot.on { background:#4caf50; box-shadow:0 0 6px #4caf50; }
            .status-dot.shed { background:#f44336; box-shadow:0 0 6px #f44336; }
            .spacer { flex:1; }
            .badge { padding:2px 7px; border-radius:8px; font-size:0.95em; font-weight:600; }
            .badge.priority { background:#ff9800; color:#fff; min-width:14px; text-align:center; }
            .toggle-label { display:flex; align-items:center; gap:4px; }
            .arrows { display:flex; flex-direction:column; gap:1px; }
            .arrow-btn { border:none; background:none; cursor:pointer; font-size:11px; padding:0 4px; opacity:0.35; line-height:1; color:var(--primary-text-color,inherit); }
            .arrow-btn:hover { opacity:0.8; }
            .mode-select { background:var(--card-background-color,rgba(40,40,55,0.7)); color:var(--primary-text-color); border:1px solid var(--divider-color,rgba(255,255,255,0.08)); border-radius:6px; padding:2px 6px; font-size:13px; font-family:'Segoe UI','Roboto',sans-serif; cursor:pointer; -webkit-appearance:none; appearance:none; }
            .mode-select:focus { outline:none; border-color:rgba(255,152,0,0.5); }
            .configure-btn { display:inline-flex; align-items:center; gap:3px; padding:2px 6px; background:rgba(255,193,7,0.12); border:1px solid rgba(255,193,7,0.25); border-radius:5px; color:#ffc107; cursor:pointer; font-size:0.9em; }
            .configure-btn:hover { background:rgba(255,193,7,0.22); }
            .hint { text-align:center; font-size:0.95em; opacity:0.4; margin-top:10px; }
            .help-btn {
                width:24px; height:24px; border-radius:50%;
                border:1px solid var(--divider-color, rgba(255,255,255,0.2));
                background:transparent; color:var(--secondary-text-color,#999);
                font-weight:700; cursor:pointer; margin-left:8px; flex:0 0 auto;
            }
            .help-btn.active { color:#ff9800; border-color:#ff9800; }
            .help-panel {
                margin:4px 0 14px; padding:12px 14px; border-radius:10px;
                background:rgba(128,128,128,0.08);
                font-size:0.9em; line-height:1.5;
            }
            .help-item { margin-bottom:8px; }
            .help-item:last-child { margin-bottom:0; }
            .help-item b { color:var(--primary-text-color,#e0e0e0); }
            .goal-btn {
                width:26px; height:26px; border-radius:8px;
                border:1px solid var(--divider-color, rgba(255,255,255,0.15));
                background:transparent; color:var(--secondary-text-color,#999);
                cursor:pointer; display:flex; align-items:center; justify-content:center;
                margin-left:6px; flex:0 0 auto;
            }
            .goal-btn.active { color:#ff9800; border-color:#ff9800; }
            .goal-progress { display:flex; align-items:center; gap:8px; }
            .comfort-chip { display:inline-flex; align-items:center; gap:4px;
                margin:2px 0 0 26px; padding:1px 8px; font-size:11.5px;
                border:1px solid; border-radius:9px; width:fit-content; }
            .comfort-strip { position:relative; height:18px; margin:6px 4px 2px; }
            .cs-track { position:absolute; top:8px; left:0; right:0; height:3px;
                border-radius:2px; background:rgba(255,255,255,0.12); }
            .cs-zone { position:absolute; top:8px; height:3px; border-radius:2px;
                background:linear-gradient(90deg,#8DC89255,#ffc10755); }
            .cs-mark { position:absolute; top:4px; width:3px; height:11px;
                border-radius:2px; transform:translateX(-50%); }
            .cs-read { position:absolute; top:-2px; transform:translateX(-50%);
                font-size:10px; color:var(--primary-text-color,#e0e0e0); }
            .goal-bar {
                flex:1 1 auto; height:5px; border-radius:3px;
                background:rgba(128,128,128,0.2); overflow:hidden; max-width:220px;
            }
            .goal-bar-fill { height:100%; border-radius:3px; transition:width 0.4s; }
            .goal-progress-text { font-size:12px; color:var(--secondary-text-color,#999); white-space:nowrap; }
            .ge-spacer { margin-left:auto; }
            .ge-unit-select {
                appearance:none; -webkit-appearance:none;
                background-color:var(--secondary-background-color, rgba(255,255,255,0.07));
                background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23bbbbbb' d='M7 10l5 5 5-5z'/%3E%3C/svg%3E");
                background-repeat:no-repeat; background-position:right 4px center;
                background-size:12px;
                color:var(--primary-text-color,#e0e0e0);
                border:1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius:6px; padding:2px 20px 2px 8px;
                font-size:11px; font-weight:600; cursor:pointer;
                text-transform:none; letter-spacing:0;
            }
            .range-wrap { padding:6px 8px 10px; }
            .range-labels {
                display:flex; justify-content:space-between;
                font-size:12px; color:var(--primary-text-color,#e0e0e0);
                margin-bottom:10px;
            }
            .range-labels b { font-variant-numeric:tabular-nums; }
            .range-track {
                position:relative; height:6px; border-radius:3px;
                background:rgba(255,255,255,0.14); margin:6px 9px;
                touch-action:none; cursor:pointer;
            }
            .range-fill {
                position:absolute; top:0; height:100%; border-radius:3px;
                background:linear-gradient(90deg, #8DC892, #ff9800);
                pointer-events:none;  /* never swallow the handle grab */
            }
            .range-handle {
                position:absolute; top:50%; width:18px; height:18px;
                border-radius:50%; transform:translate(-50%, -50%);
                background:#fff; box-shadow:0 1px 3px rgba(0,0,0,0.5);
                cursor:grab; touch-action:none; pointer-events:auto;
                z-index:2;  /* sit above the fill so pointerdown lands */
            }
            .range-handle:active { cursor:grabbing; }
            /* #355-style split affordance: sits ABOVE the stacked handles so a
               tap can separate them when Min and Max share a spot. */
            .range-split {
                position:absolute; top:50%; transform:translate(-50%,-50%);
                width:22px; height:22px; border-radius:50%;
                display:flex; align-items:center; justify-content:center;
                background:rgba(0,0,0,0.55); color:#fff; cursor:pointer;
                box-shadow:0 1px 3px rgba(0,0,0,0.5);
                pointer-events:auto; z-index:3;
            }
            .range-split:hover { background:rgba(0,0,0,0.75); }
            .range-handle-min { border:3px solid #8DC892; }
            .range-handle-max { border:3px solid #ff9800; }
            .range-handle-peak { border:3px solid #488fc2; }
            /* EV charge-target look (#559 UI merge) */
            .goal-editor {
                margin:8px 0 4px 28px; padding:10px 12px;
                border:1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius:10px; background:rgba(255,255,255,0.025);
            }
            .ge-title {
                font-size:11px; text-transform:uppercase; letter-spacing:0.05em;
                color:var(--secondary-text-color,#999);
                display:flex; align-items:center; gap:5px; margin-bottom:4px;
            }
            .ge-docs {
                display:inline-flex; align-items:center;
                color:var(--secondary-text-color,#999); opacity:0.55;
            }
            .ge-docs:hover { opacity:1; }
            .ge-row {
                display:flex; align-items:center; min-height:34px; padding:2px 0;
            }
            .ge-row + .ge-row { border-top:1px solid rgba(255,255,255,0.06); }
            .ge-label { font-size:12px; color:var(--primary-text-color,#e0e0e0); }
            .ge-ctl { margin-left:auto; display:flex; align-items:center; gap:7px; }
            .ge-unit { font-size:12px; color:var(--secondary-text-color,#999); }
            .ge-mode-select {
                appearance:none; -webkit-appearance:none;
                background-color:var(--secondary-background-color, rgba(255,255,255,0.07));
                background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23bbbbbb' d='M7 10l5 5 5-5z'/%3E%3C/svg%3E");
                background-repeat:no-repeat; background-position:right 6px center;
                background-size:14px;
                color:var(--primary-text-color,#e0e0e0);
                border:1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius:8px; padding:4px 24px 4px 10px;
                font-size:12px; font-weight:600; cursor:pointer;
            }
            .goal-editor input[type=number], .goal-editor input[type=time], .goal-editor input[type=text] {
                background:var(--secondary-background-color, rgba(255,255,255,0.07));
                border:1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius:8px; color:var(--primary-text-color,#e0e0e0);
                padding:4px 8px; width:72px; font-size:12px;
                font-variant-numeric:tabular-nums;
            }
            .goal-editor input.ge-entity { width:160px; max-width:100%; }
            /* Mobile: the stop-when row (entity + ≥ + number) overflows a
               phone width and squeezes the label onto two lines. Stack the
               label above the control and let the entity field flex. */
            @media (max-width: 480px) {
                .goal-editor { margin-left:6px; padding:10px; }
                .ge-row { flex-wrap:wrap; align-items:flex-start; }
                .ge-label { flex:1 0 100%; margin-bottom:4px; }
                .ge-ctl { margin-left:0; width:100%; }
                .goal-editor input.ge-entity { flex:1; width:auto; }
            }
            .ge-hint {
                display:flex; align-items:center; gap:6px;
                font-size:12px; color:var(--secondary-text-color,#999); padding:4px 0 6px;
            }
            /* (#620) battery-overnight toggle switch */
            .batt-toggle {
                width:34px; height:19px; border-radius:11px; border:none; padding:0;
                position:relative; cursor:pointer; background:rgba(255,255,255,0.15);
                transition:background .2s;
            }
            .batt-toggle.on { background:#4db6ac; }
            .batt-toggle .knob {
                position:absolute; top:2px; left:2px; width:15px; height:15px;
                border-radius:50%; background:#fff; transition:left .2s;
            }
            .batt-toggle.on .knob { left:17px; }
            /* (#620) "Finish overnight from" segmented picker */
            .ov-picker { gap:0; border-radius:8px; overflow:hidden;
                border:1px solid var(--divider-color, rgba(128,128,128,0.25)); }
            .ov-opt {
                border:none; padding:5px 12px; cursor:pointer; font-size:12px;
                background:rgba(255,255,255,0.06); color:var(--primary-text-color,#e0e0e0);
                border-right:1px solid var(--divider-color, rgba(128,128,128,0.25));
            }
            .ov-opt:last-child { border-right:none; }
            .ov-opt.on { background:#4db6ac; color:#fff; font-weight:600; }
            .empty { text-align:center; padding:20px 0; opacity:0.4; font-size:1em; }
        `}_updateDeviceData(){if(!this._hass)return;const t=this._hass.states[`${this._prefix}target_peak_limit`],e=this._hass.states[`${this._prefix}consecutive_peak_15min`],s=this._hass.states[`${this._prefix}load_management_status`],i=this._hass.states[`${this._prefix}controllable_devices_count`];t&&(this.targetPeakLimit=At(t)),t&&(this.peakLimitUnlimited=t.attributes?.peak_limit_unlimited||!1);const r=this._peakHold;if(r){this.peakLimitUnlimited===r.unlimited&&(r.unlimited||Math.abs(this.targetPeakLimit-r.kw)<.05)||Date.now()>=r.until?this._peakHold=null:(this.targetPeakLimit=r.kw,this.peakLimitUnlimited=r.unlimited)}e&&(this.currentPeak=At(e)),t&&(this.slotAllowedW=t.attributes?.peak_slot_allowed_w??null,this.slotUsedKwh=t.attributes?.peak_slot_used_kwh??null);const a=this._hass.states[`${this._prefix}grid_power`];this.gridImportKw=a?function(t){const e="number"==typeof t?t:parseFloat(t);return Number.isFinite(e)?Math.max(0,-e)/1e3:null}(a.state):null,s&&(this.loadManagementStatus=s.state||"normal"),i?.attributes?.devices&&(this.devices=Object.entries(i.attributes.devices).map(([t,e])=>({id:t,name:e.name||t.replace(/^(load_device_|energy_dashboard_)/,"").replace(/_/g," "),power:zr(this._hass.states[e.power_entity],e),rating:e.power_rating||0,priority:e.priority||5,isOn:e.is_on||!1,isShed:e.is_shed||!1,shedReason:e.shed_reason||null,shedPhase:e.shed_phase||null,phase:e.goals&&e.goals.phase||e.phase||"unknown",behindRelay:!(!e.goals||!e.goals.behind_operator_relay),lockedByOperator:!0===e.locked_by_operator,phaseMeasured:!0===e.phase_measured,hasControlHandle:void 0!==e.has_control_handle?!1!==e.has_control_handle:!1!==e.is_controllable,isControllable:void 0!==e.user_hands_off?!0!==e.user_hands_off:!1!==e.is_controllable,isCritical:e.is_critical||!1,deviceType:e.device_type||"unknown",isAvailable:e.is_available||!1,hasManualMapping:e.has_manual_mapping||!1,energySensor:e.energy_sensor||"",control:e.control||null,controlEntity:e.control?.entity||e.switch_entity||"",controlType:e.control?.type||"switch",controlMode:e.control_mode||"peak_only",dependsOn:e.depends_on||[],goals:e.goals||null,progress:e.progress||null,comfort:e.comfort||null,blockedBy:e.blocked_by||null,soc:e.soc,icon:this._resolveDeviceIcon(e)})).sort((t,e)=>t.priority-e.priority))}render(){if(!this._config)return K;const t=this.peakLimitUnlimited,e=this._getPeakColor(),s=null==this.targetPeakLimit||null==this.currentPeak?null:this.targetPeakLimit-this.currentPeak,i=t||null==this.currentPeak?0:this.targetPeakLimit>0?Math.min(this.currentPeak/this.targetPeakLimit*100,100):0,r=t?null:Wt({targetKw:this.targetPeakLimit,usedKwh:this.slotUsedKwh,allowedW:this.slotAllowedW});return H`
            <ha-card>
                <div class="card-content">
                    <div class="status-bar">
                        <div class="peak-dot" style="background:${e};box-shadow:0 0 8px ${e}"></div>
                        <span id="lm-status" class="status-text">${Et("load_management_status",this.loadManagementStatus||"normal",t=>this._t(t)).toUpperCase()}</span>
                        <div class="spacer"></div>
                        <span class="dim">${this._t("peak_15min_avg")}</span>
                        <span id="peak-current" class="mono">${Tt(this.currentPeak,2)} kW</span>
                        <span class="dim">/ ${t?this._t("uncapped"):Tt(this.targetPeakLimit,1)}</span>
                        <button class="help-btn ${this._showHelp?"active":""}" data-action="toggle-help"
                                title="${this._t("help")}">?</button>
                    </div>

                    <div class="peak-box">
                        <div class="peak-row">
                            <span class="dim">${this._t("peak_15min_avg")}</span>
                            <span id="peak-current2" class="mono">${Tt(this.currentPeak,2)} kW</span>
                        </div>
                        ${null===this.gridImportKw?K:H`
                        <div class="peak-row">
                            <span class="dim">${this._t("peak_right_now")}</span>
                            <span id="peak-now" class="mono dim">${this.gridImportKw.toFixed(2)} kW</span>
                        </div>`}
                        <div class="peak-row">
                            <span class="dim">${this._t("target_limit")}</span>
                            <span id="peak-target" class="mono">${t?this._t("uncapped"):Tt(this.targetPeakLimit,2)+" kW"}</span>
                        </div>
                        ${t?K:H`
                        <div class="peak-row">
                            <span class="dim">${this._t("margin")}</span>
                            <span id="peak-margin" class="mono" style="color:${null==s?"":s>0?"#4caf50":"#f44336"}">${Tt(s,2)} kW</span>
                        </div>`}
                        <div class="bar">
                            <div id="peak-bar" class="bar-fill" style="width:${i}%;background:${e}"></div>
                        </div>
                        ${null===r?K:H`
                        <div class="peak-row" style="margin-top:10px">
                            <span class="dim">${this._t("peak_slot")} ${r.label}</span>
                            <span id="peak-slot-used" class="mono">${r.usedKwh.toFixed(2)} / ${r.budgetKwh.toFixed(2)} kWh</span>
                        </div>
                        <div class="bar">
                            <div id="peak-slot-bar" class="bar-fill"
                                 style="width:${100*r.fraction}%;background:${r.overBudget?"#f44336":e}"></div>
                        </div>
                        ${null===r.allowedKw?K:H`
                        <div class="peak-row">
                            <span class="dim">${this._t("peak_slot_allows")}</span>
                            <span id="peak-slot-allows" class="mono dim">${r.allowedKw.toFixed(2)} kW</span>
                        </div>`}`}
                    </div>

                    <div class="peak-box" style="margin-bottom:16px">
                        <span class="dim">${this._t("adjust_target_peak")}</span>
                        ${this._renderPeakSlider()}
                    </div>

                    ${this._showHelp?H`
                    <div class="help-panel">
                        <div class="help-item"><b>${this._t("off")}</b> — ${this._t("help_mode_off")}</div>
                        <div class="help-item"><b>${this._t("peak_only")}</b> — ${this._t("help_mode_peak_only")}</div>
                        <div class="help-item"><b>${this._t("mode_solar_only")}</b> — ${this._t("help_mode_surplus")}</div>
                        <div class="help-item"><b>${this._t("mode_solar_battery")}</b> — ${this._t("battery_overnight_hint")}</div>
                        <div class="help-item"><b>${this._t("priority")}</b> — ${this._t("help_device_priority")}</div>
                        <div class="help-item"><b>${this._t("requires")}</b> — ${this._t("help_device_requires")}</div>
                        <div class="help-item"><b>${this._t("configure")}</b> — ${this._t("help_device_configure")}</div>
                        <div class="help-item"><b>${this._t("peak_15min_avg")}</b> — ${this._t("help_peak_15min_avg")}</div>
                        <div class="help-item"><b>${this._t("peak_slot")}</b> — ${this._t("help_peak_slot")}</div>
                        <div class="help-item"><b>${this._t("target_limit")}</b> — ${this._t("help_device_peak")}</div>
                        <div class="help-item"><b>${this._t("daily_target")}</b> — ${this._t("help_device_target")}</div>
                    </div>`:K}

                    <div class="section-label">
                        <ha-icon icon="mdi:drag-vertical" style="--mdc-icon-size:18px"></ha-icon>
                        ${this._t("drag_to_reorder")}
                    </div>

                    <div id="device-list" class="device-list">
                        ${0===this.devices.length?H`<div class="empty">${this._t("no_devices_yet")}</div>`:xr(this.devices,t=>t.id,(t,e)=>this._renderDevice(t,e+1))}
                    </div>

                    ${this.devices.length>0?H`<div class="hint">${this._t("drag_hint")}</div>`:K}

                    <div class="hint" style="margin-top:12px;padding:10px;background:rgba(128,128,128,0.06);border-radius:10px">
                        ${this._t("devices_auto_discovered").replace(/<br\s*\/?>/g," — ")}
                    </div>
                </div>
            </ha-card>
        `}_renderDevice(t,e){const s=t.isOn||t.power>.01,i="battery"===t.deviceType,r=t.dependsOn.length>0,a=this._getDependencyDepth(t),n=a>0?`margin-left:${24*a}px;border-left:2px solid rgba(255,152,0,${.3+.1*a});`:"";return H`
        <div class="device${r?" is-child":""}" data-id="${t.id}" style="${n}">
            <div class="drag-handle"
                 title="${r?this._t("locked_under_parent"):this._t("drag_to_reorder")}"
                 @pointerdown=${r?null:e=>this._dragStart(e,t.id)}
                 style="${r?"opacity:0.3;cursor:default":""}">${r?"·":"≡"}</div>
            <div class="device-body">
                <div class="device-top">
                    <div class="device-name">
                        ${r?H`<span style="color:#ff9800;font-size:12px;margin-right:4px">&#8618;</span>`:K}
                        <ha-icon icon="${t.icon}" style="--mdc-icon-size:20px;color:${s?"#ff9800":"#666"}"></ha-icon>
                        <span>${t.name}</span>
                        ${i?K:H`
                        <span class="configure-btn" data-action="configure" data-device="${t.id}" data-name="${t.name}">
                            <ha-icon icon="mdi:${t.hasManualMapping?"wrench":"cog"}" style="--mdc-icon-size:14px"></ha-icon> ${t.isControllable?this._t("configure_device"):this._t("configure")}
                        </span>`}
                    </div>
                    <div class="device-power" data-field="power-${t.id}">
                        ${i?H`<span style="opacity:0.7">${null!=t.soc?t.soc+"% · ":""}${s?ut(null==t.power?null:1e3*t.power):this._t("off")}</span>`:s?ut(null==t.power?null:1e3*t.power):t.isShed?this._t("shed_label"):t.rating>0?H`<span style="opacity:0.5" title="${this._t("rated_power_hint")}">~${ut(t.rating)}</span>`:this._t("off")}
                    </div>
                </div>
                ${t.blockedBy?H`<div style="font-size:13px;color:#ff9800;padding:2px 0 0 28px">&#9203; Waiting for: ${t.blockedBy}</div>`:K}
                ${t.dependsOn.length?H`<div style="font-size:13px;opacity:0.55;padding:0 0 0 28px">&#8618; ${this._t("requires")}: ${t.dependsOn.join(", ")}</div>`:K}
                ${t.isShed&&t.shedReason?H`<div style="font-size:13px;color:#f44336;padding:2px 0 0 28px">${(this._t((o=t.shedReason,"EMERGENCY"===String(o||"").toUpperCase()?"shed_emergency":"PHASE"===String(o||"").toUpperCase()?"shed_phase":"shed_peak"))||"").replace("{phase}",t.shedPhase||"?")}</div>`:K}
                <div class="device-bottom">
                    <div class="status-dot ${t.lockedByOperator?"locked":s?"on":t.isShed?"shed":""}" data-field="status-${t.id}"></div>
                    ${t.lockedByOperator?H`<span class="operator-lock" data-field="onoff-${t.id}">${this._t("locked_by_grid_operator")}</span>`:H`<span class="dim" data-field="onoff-${t.id}">${s?this._t("on"):t.isShed?this._t("shed_label"):this._t("off")}</span>`}
                    <span class="badge priority" data-field="pri-${t.id}">${e}</span>
                    ${i||t.lockedByOperator?K:this._renderControlVerdict(t)}
                    <div class="spacer"></div>
                    ${i?H`<span class="dim" title="${this._t("battery_role_help")}">${this._t("battery_role_label")}</span>`:K}
                    ${"ev_charger"===t.deviceType||"ev_charging"===t.deviceType||i?K:H`
                    <label class="toggle-label" title="${this._t("mode_tooltip")}">
                        <span class="dim">${this._t("mode")}</span>
                        <select class="mode-select" data-action="combined_mode" data-device="${t.id}">
                            <option value="off" ?selected="${"off"===this._mergedMode(t)}">${this._t("off")}</option>
                            <option value="peak_only" ?selected="${"peak_only"===this._mergedMode(t)}">${this._t("peak_only")}</option>
                            <option value="solar_only" ?selected="${"solar_only"===this._mergedMode(t)}">${this._t("mode_solar_only")}</option>
                            <option value="solar_battery" ?selected="${"solar_battery"===this._mergedMode(t)}">${this._t("mode_solar_battery")}</option>
                        </select>
                    </label>`}
                    ${i?K:H`
                    <label class="toggle-label" title="${this._t("requires_tooltip")}">
                        <span class="dim">${this._t("requires")}</span>
                        <select class="mode-select" data-action="depends_on" data-device="${t.id}">
                            <option value="" ?selected="${!t.dependsOn.length}">${this._t("action_none")}</option>
                            ${this.devices.filter(e=>e.id!==t.id).map(e=>H`<option value="${e.id}" ?selected="${t.dependsOn.includes(e.id)}">${e.name}</option>`)}
                        </select>
                    </label>`}
                    ${i?K:this._renderPhase(t)}
                    <div class="arrows">
                        <button class="arrow-btn" data-action="move-up"   data-device="${t.id}" title="${this._t("move_up")}">&#9650;</button>
                        <button class="arrow-btn" data-action="move-down" data-device="${t.id}" title="${this._t("move_down")}">&#9660;</button>
                    </div>
                    ${"ev_charger"===t.deviceType||"ev_charging"===t.deviceType||i||"solar_only"!==this._mergedMode(t)&&"solar_battery"!==this._mergedMode(t)?K:H`
                    <button class="goal-btn ${this._goalOpen[t.id]?"active":""}"
                            data-action="toggle-goal" data-device="${t.id}"
                            title="${this._t("daily_target")}">
                        <ha-icon icon="mdi:target" style="--mdc-icon-size:16px;pointer-events:none"></ha-icon>
                    </button>`}
                </div>
                ${this._renderComfortChip(t)}
                ${this._renderGoalProgress(t)}
                ${this._goalOpen[t.id]?this._renderGoalEditor(t):K}
            </div>
        </div>`;var o}_renderPhase(t){const e=(t.goals||{}).phase||t.phase||"unknown",s=t=>"unknown"===t?this._t("load_phase_unknown"):"3ph"===t?this._t("load_phase_3ph"):t;return"ev_charger"===t.deviceType||"ev_charging"===t.deviceType?"unknown"===e?K:H`
                <span class="dim" title="${this._t("load_phase_measured_hint")}">${s(e)}</span>`:H`
            <label class="toggle-label" title="${this._t("load_phase_tooltip")}">
                <span class="dim">${this._t("load_phase_label")}</span>
                <select class="mode-select" data-goal="phase" data-device="${t.id}">
                    ${["unknown","L1","L2","L3","3ph"].map(t=>H`
                        <option value="${t}" ?selected="${e===t}">${s(t)}</option>`)}
                </select>
            </label>`}_mergedMode(t){const e=t.controlMode||"peak_only";return"surplus"!==e?e:(t.goals||{}).battery_assist_enabled?"solar_battery":"solar_only"}_mergedModeLabel(t){const e=this._mergedMode(t),s={off:"off",peak_only:"peak_only",solar_only:"mode_solar_only",solar_battery:"mode_solar_battery"}[e]||e;return this._t(s)}_applyMergedMode(t,e){const s="off"===e||"peak_only"===e?e:"surplus";if(t.controlMode=s,this._sendDeviceUpdate(t.id,"control_mode",s),"surplus"===s){const s="solar_battery"===e;t.goals=t.goals||{},t.goals.battery_assist_enabled=s,this._sendDeviceUpdate(t.id,"battery_assist_enabled",String(s)),"always"===t.goals.top_up_policy&&(t.goals.top_up_policy="solar_only",this._sendDeviceUpdate(t.id,"top_up_policy","solar_only"))}this.requestUpdate()}_hasTarget(t){return parseFloat((t.goals||{}).daily_min_runtime_min)>0}_goalPct(t){const e=t.goals,s=t.progress;if(!e||!s)return null;const i=parseFloat(e.daily_min_runtime_min);return i>0?Math.min(100,s.runtime_today_min/i*100):null}_renderGoalSlider(t){const e=t.goals||{},s=this._goalDrag;let i=(parseFloat(e.daily_min_runtime_min)||0)/60,r=parseFloat(e.daily_max_runtime_min)||0,a=r>0?r/60:12;s&&s.id===t.id&&("min"===s.handle?i=s.value:a=s.value),a<i&&(a=i);const n=Math.min(100,i/12*100),o=Math.min(100,a/12*100),l=a>=11.999999,c=t=>t%1==0?String(t):t.toFixed(1),d=a-i<.499999;return H`
            <div class="range-wrap">
                ${this._serviceError?H`<div class="svc-error" role="alert">${this._serviceError}</div>`:K}
                <div class="range-labels">
                    <span>${this._t("at_least")} <b style="color:#8DC892">${i<=0?this._t("no_target"):c(i)+" h"}</b></span>
                    <span>${this._t("up_to")} <b style="color:#ff9800">${l?this._t("uncapped"):c(a)+" h"}</b></span>
                </div>
                <div class="range-track">
                    <div class="range-fill" style="left:${n}%;width:${Math.max(0,o-n)}%;background:linear-gradient(90deg,#8DC892,#ff9800)"></div>
                    <div class="range-handle range-handle-min" style="left:${n}%"
                         @pointerdown=${e=>this._goalSliderStart(e,t,"min")}></div>
                    <div class="range-handle range-handle-max" style="left:${o}%"
                         @pointerdown=${e=>this._goalSliderStart(e,t,"max")}></div>
                    ${d?H`
                        <span class="range-split" style="left:${n}%"
                              title="${this._t("separate_handles")}"
                              @click=${e=>this._splitGoalHandles(e,t,i,a)}>
                            <ha-icon icon="mdi:arrow-split-vertical" style="--mdc-icon-size:14px"></ha-icon>
                        </span>`:K}
                </div>
            </div>`}_splitGoalHandles(t,e,s,i){t.stopPropagation();const r=.5,a=e.goals=e.goals||{};if(s-r>=0){const t=Math.round(60*(s-r));a.daily_min_runtime_min=t,this._sendDeviceUpdate(e.id,"daily_min_runtime_min",String(t))}else{const t=Math.min(11.5,i-r),s=Math.round(60*t);a.daily_max_runtime_min=s,this._sendDeviceUpdate(e.id,"daily_max_runtime_min",String(s))}this.requestUpdate()}_goalSliderStart(t,e,s){t.stopPropagation(),t.preventDefault();const i=t.currentTarget.parentElement,r=e.goals=e.goals||{},a=i.getBoundingClientRect(),n=(parseFloat(r.daily_min_runtime_min)||0)/60,o=parseFloat(r.daily_max_runtime_min)||0,l=o>0?o/60:12,c=t=>{let e=(t-a.left)/(a.width||1);e=Math.max(0,Math.min(1,e));let i=.5*Math.round(12*e/.5);return i="min"===s?Math.min(i,l):Math.max(i,n),i},d=t=>{this._goalDrag={id:e.id,handle:s,value:c(t)},this.requestUpdate()};d(t.clientX);const p=t=>d(t.clientX),_=t=>{window.removeEventListener("pointermove",p),window.removeEventListener("pointerup",_),window.removeEventListener("pointercancel",_);const i=c(t.clientX);if(this._goalDrag=null,"min"===s){const t=Math.round(60*i);r.daily_min_runtime_min=t,this._sendDeviceUpdate(e.id,"daily_min_runtime_min",String(t))}else{const t=i>=11.999999?0:Math.round(60*i);r.daily_max_runtime_min=t,this._sendDeviceUpdate(e.id,"daily_max_runtime_min",String(t))}this.requestUpdate()};window.addEventListener("pointermove",p),window.addEventListener("pointerup",_),window.addEventListener("pointercancel",_)}_renderPeakSlider(){const t=this._peakDrag;let e=this.peakLimitUnlimited?80:Math.min(80,Math.max(1,this.targetPeakLimit||1));null!=t&&(e=t);const s=(e-1)/79*100,i=e>=79.999999,r=null==t&&!this.peakLimitUnlimited&&null==this.targetPeakLimit?`${Nt} kW`:i?this._t("uncapped"):`${e.toFixed(1)} kW`;return H`
            <div class="range-wrap">
                <div class="range-labels">
                    <span>${this._t("target_limit")}</span>
                    <span><b style="color:#488fc2">${r}</b></span>
                </div>
                <div class="range-track">
                    <div class="range-fill" style="left:0;width:${s}%;background:#488fc2"></div>
                    <div class="range-handle range-handle-peak" style="left:${s}%"
                         @pointerdown=${t=>this._peakSliderStart(t)}></div>
                </div>
            </div>`}_peakSliderStart(t){t.stopPropagation(),t.preventDefault();const e=t.currentTarget.parentElement.getBoundingClientRect(),s=t=>{let s=(t-e.left)/(e.width||1);return s=Math.max(0,Math.min(1,s)),.5*Math.round((1+79*s)/.5)},i=t=>{this._peakDrag=s(t),this.requestUpdate()};i(t.clientX);const r=t=>i(t.clientX),a=t=>{window.removeEventListener("pointermove",r),window.removeEventListener("pointerup",a),window.removeEventListener("pointercancel",a);const e=s(t.clientX);this._peakDrag=null,this._commitPeakLimit(e,e>=79.999999)};window.addEventListener("pointermove",r),window.addEventListener("pointerup",a),window.addEventListener("pointercancel",a)}_commitPeakLimit(t,e){this.targetPeakLimit=t,this.peakLimitUnlimited=e;const s={kw:t,unlimited:e,until:Date.now()+15e3};this._peakHold=s,this._sendTargetPeakUpdate(t,e,s),this.requestUpdate()}_onStopEntity(t,e){e.stopPropagation();const s=e.detail&&e.detail.value||"";t.goals=t.goals||{},t.goals.stop_entity=s,this._sendDeviceUpdate(t.id,"stop_entity",s)}_overnightSource(t){const e=t.goals||{};return e.battery_eligible_overnight?"battery":"cheap_hours"===e.top_up_policy?"grid":"off"}_renderOvernightPicker(t){const e=this._overnightSource(t),s=(s,i)=>H`
            <button class="ov-opt ${e===s?"on":""}"
                    data-action="set-overnight" data-overnight="${s}"
                    data-device="${t.id}">${i}</button>`;return H`
            <div class="ge-row">
                <span class="ge-label">${this._t("finish_overnight_from")}</span>
                <span class="ge-ctl ov-picker">
                    ${s("off",this._t("overnight_off"))}
                    ${s("battery",this._t("overnight_battery"))}
                    ${s("grid",this._t("overnight_grid"))}
                </span>
            </div>
            <div class="ge-hint">${this._t("overnight_"+e+"_hint")}</div>`}_setOvernightSource(t,e){const s=t.goals=t.goals||{},i="battery"===e,r="grid"===e?"cheap_hours":"solar_only";s.battery_eligible_overnight=i,s.top_up_policy=r,this._sendDeviceUpdate(t.id,"battery_eligible_overnight",String(i)),this._sendDeviceUpdate(t.id,"top_up_policy",r),this.requestUpdate()}_renderGoalProgress(t){const e=this._mergedMode(t);if("solar_only"!==e&&"solar_battery"!==e)return K;const s=this._goalPct(t);if(null===s)return K;const i=t.goals,r=t.progress,a=r.targets_met||s>=100,n=t=>{const e=t/60;return e%1==0?String(e):e.toFixed(1)},o=n(r.runtime_today_min)+"/"+n(parseFloat(i.daily_min_runtime_min))+" "+this._t("hours_on_solar_today");return H`
            <div class="goal-progress" style="padding:2px 0 0 28px">
                <div class="goal-bar"><div class="goal-bar-fill" style="width:${s}%;background:#8DC892"></div></div>
                <span class="goal-progress-text">${o}${a?" ✓":""}</span>
            </div>`}_renderGoalEditor(t){const e=this._mergedMode(t);if("solar_only"!==e&&"solar_battery"!==e)return K;const s=t.goals||{};return H`
            <div class="goal-editor">
                <div class="ge-title">
                    <ha-icon icon="mdi:target" style="--mdc-icon-size:14px;color:#8DC892"></ha-icon>
                    ${this._t("daily_target")}
                </div>
                ${this._renderGoalSlider(t)}
                ${this._renderComfortBand(t)}
                ${this._renderOvernightPicker(t)}
                ${this._renderAntiCycle(t)}
                ${this._renderOwnTariff(t)}
                <div class="ge-row">
                    <span class="ge-label">${this._t("stop_condition")}</span>
                    <span class="ge-ctl">
                        ${this.hass&&customElements.get("ha-entity-picker")?H`
                        <ha-entity-picker class="ge-entity"
                               .hass=${this.hass}
                               .value=${s.stop_entity||""}
                               .includeDomains=${["sensor","number","input_number"]}
                               .placeholder=${this._t("stop_entity_placeholder")}
                               allow-custom-entity
                               @value-changed=${e=>this._onStopEntity(t,e)}
                               @click=${t=>t.stopPropagation()}></ha-entity-picker>
                        `:H`
                        <input type="text" class="ge-entity" placeholder="${this._t("stop_entity_placeholder")}"
                               .value="${s.stop_entity||""}"
                               data-goal="stop_entity" data-device="${t.id}">`}
                        <span class="ge-unit">≥</span>
                        <input type="number" min="0" step="1" style="width:56px"
                               .value="${String(s.stop_at||0)}"
                               data-goal="stop_at" data-device="${t.id}">
                    </span>
                </div>
                <div class="ge-hint">${this._t("stop_condition_hint")}</div>
            </div>`}_comfortChipMeta(t){const e=t.comfort;if(!e||!e.state||"disengaged"===e.state)return null;const s="cool"===(e.hvac||"cool");return{forced:{icon:"🔥",color:"#ffc107",label:this._t(s?"chip_cooling_now":"chip_heating_now")},willing:{icon:"❄",color:"#8DC892",label:this._t(s?"chip_pre_cooling":"chip_pre_heating")},banked:{icon:"✓",color:"#4db6ac",label:this._t("chip_banked")}}[e.state]||null}_displayTemp(t){if(null==t)return null;const e=this.hass?.config?.unit_system?.temperature||"°C",s="°F"===e?9*t/5+32:t;return`${Math.round(10*s)/10} ${e}`}_renderControlVerdict(t){const e=this._mergedMode(t);let s,i,r;return t.hasControlHandle?t.isControllable&&"off"!==e?(s="control_verdict_may_act",i="mdi:check-circle-outline",r="#8DC892"):(s="control_verdict_off",i="mdi:hand-back-left-outline",r="#ff9800"):(s="control_verdict_none",i="mdi:minus-circle-outline",r="#666"),H`
            <span class="dim" style="display:inline-flex;align-items:center;gap:3px;color:${r}"
                  title="${this._t("control_verdict_help")}">
                <ha-icon icon="${i}" style="--mdc-icon-size:14px"></ha-icon>${this._t(s)}
            </span>`}_renderComfortChip(t){const e=this._comfortChipMeta(t);if(!e)return K;const s=this._displayTemp(t.comfort.reading_c);return H`
            <div class="comfort-chip" style="border-color:${e.color}55;color:${e.color}">
                <span>${e.icon}</span> ${e.label}${s?H` \u00B7 ${s}`:K}
            </div>`}_renderComfortBand(t){const e=!["ev_charger","ev_charging","battery"].includes(t.deviceType);if(!t.comfort&&!e)return K;const s=t.goals||{},i=this.hass?.config?.unit_system?.temperature||"°C",r=parseFloat(s.comfort_target)||0,a=parseFloat(s.comfort_offset)||0,n=parseFloat(s.comfort_limit)||0,o=r>0&&n>0,l=o?Math.min(r-a,n)-3:18,c=o?Math.max(r,n)+3:30,d=t=>Math.max(0,Math.min(100,(t-l)/(c-l)*100)),p=t.comfort?t.comfort.reading_c:null,_=null==p?null:"°F"===i?9*p/5+32:p,h=/^hot_water/.test(String(t.id||""))&&r>0,u=this._t("comfort_example").replace("{keep}",r+i).replace("{extra}",a+i).replace("{max}",r+a+i),g=(e,s,i)=>H`
            <input type="number" step="${i}" style="width:56px"
                   .value="${s?String(s):""}" placeholder="\u2014"
                   @change=${s=>{const i=s.target.value;""!==i&&null!=i&&(t.goals={...t.goals||{},[e]:i},this._sendDeviceUpdate(t.id,e,String(i)))}}
                   @click=${t=>t.stopPropagation()}>`;return H`
            <div class="ge-title" style="margin-top:10px">
                <ha-icon icon="mdi:thermometer" style="--mdc-icon-size:14px;color:#4db6ac"></ha-icon>
                ${this._t("comfort_section")}
                <a class="ge-docs" href="${Mr}" target="_blank"
                   rel="noopener" title="${this._t("config_docs")}"
                   @click=${t=>t.stopPropagation()}>
                    <ha-icon icon="mdi:book-open-variant" style="--mdc-icon-size:12px"></ha-icon>
                </a>
            </div>
            <div class="ge-row">
                <span class="ge-label">${this._t("comfort_thermometer")}</span>
                <span class="ge-ctl">
                    ${this.hass&&customElements.get("ha-entity-picker")?H`
                    <ha-entity-picker class="ge-entity"
                           .hass=${this.hass}
                           .value=${s.comfort_entity||""}
                           .includeDomains=${["sensor","input_number"]}
                           .placeholder=${this._t("comfort_own_thermometer")}
                           allow-custom-entity
                           @value-changed=${e=>{const s=e.detail?.value??"";t.goals={...t.goals||{},comfort_entity:s},this._sendDeviceUpdate(t.id,"comfort_entity",s)}}
                           @click=${t=>t.stopPropagation()}></ha-entity-picker>
                    `:H`
                    <input type="text" class="ge-entity"
                           placeholder="${this._t("comfort_own_thermometer")}"
                           .value="${s.comfort_entity||""}"
                           @change=${e=>this._sendDeviceUpdate(t.id,"comfort_entity",e.target.value)}>`}
                </span>
            </div>
            ${o?H`
            <div class="comfort-strip">
                <div class="cs-track"></div>
                <div class="cs-zone" style="left:${d(Math.min(r-a,n))}%;width:${Math.abs(d(n)-d(r-a))}%"></div>
                <div class="cs-mark" style="left:${d(r-a)}%;background:#8DC892" title="bank"></div>
                <div class="cs-mark" style="left:${d(r)}%;background:#4db6ac" title="target"></div>
                <div class="cs-mark" style="left:${d(n)}%;background:#ffc107" title="limit"></div>
                ${null!=_?H`<div class="cs-read" style="left:${d(_)}%" title="${this._displayTemp(p)}">\u25B2</div>`:K}
            </div>`:K}
            <div class="ge-row">
                <span class="ge-label">${this._t("comfort_keep_at")}</span>
                <span class="ge-ctl">${g("comfort_target",r,.5)}
                    <span class="ge-unit">${i}</span></span>
            </div>
            <div class="ge-row">
                <span class="ge-label">${this._t("comfort_precool_by")}</span>
                <span class="ge-ctl">${g("comfort_offset",a,.5)}
                    <span class="ge-unit">${i}</span></span>
            </div>
            <div class="ge-row">
                <span class="ge-label">${this._t("comfort_limit_label")}</span>
                <span class="ge-ctl">${g("comfort_limit",n,.5)}
                    <span class="ge-unit">${i}</span></span>
            </div>
            <div class="ge-hint">${this._t("comfort_hint")}</div>
            ${h?H`
            <div class="ge-hint">${u}</div>
            <div class="ge-hint">${this._t("comfort_both_limits")}</div>`:K}`}_antiCycleBounds(){const t=this._hass?.states?.[`${this._prefix}controllable_devices_count`];return function(t){const e=t&&t.anti_cycle_bounds;if(!e||null==e.min||null==e.max)return null;const s=Number(e.min),i=Number(e.max);return Number.isFinite(s)&&Number.isFinite(i)?{min:s,max:i}:null}(t?.attributes)}_onAntiCycleChange(t,e,s,i){const r=function(t,e){if(""===t||null==t)return null;const s=Number(t);if(!Number.isFinite(s)||s<1)return null;const i=e?Math.min(e.max,Math.max(e.min,s)):s;return i<1?null:i}(i.target.value,s);if(null==r){const s=(t.goals||{})[e];return void(i.target.value=null!=s?String(s):"")}i.target.value=String(r),t.goals={...t.goals||{},[e]:r},this._sendDeviceUpdate(t.id,e,String(r))}_renderAntiCycle(t){const e=t.goals||{},s=this._antiCycleBounds(),i=t=>function(t,e){const s=(t||{})[e];if(null==s)return"—";const i=Number(s);return Number.isFinite(i)?String(i):"—"}(e,t),r=(r,a)=>H`
            <input type="number" step="1" style="width:56px"
                   min=${s?Math.max(1,s.min):K}
                   max=${s?s.max:K}
                   .value="${null!=e[r]&&""!==e[r]?String(e[r]):""}"
                   placeholder="${i(a)}"
                   @change=${e=>this._onAntiCycleChange(t,r,s,e)}
                   @click=${t=>t.stopPropagation()}>`;return H`
            <div class="ge-row">
                <span class="ge-label">${this._t("anti_cycle_min_run")}</span>
                <span class="ge-ctl">
                    ${r("min_on_time_min","min_on_effective_min")}
                    <span class="ge-unit">${this._t("minutes_short")}</span>
                </span>
            </div>
            <div class="ge-row">
                <span class="ge-label">${this._t("anti_cycle_min_pause")}</span>
                <span class="ge-ctl">
                    ${r("min_off_time_min","min_off_effective_min")}
                    <span class="ge-unit">${this._t("minutes_short")}</span>
                </span>
            </div>
            <div class="ge-hint">${this._t("anti_cycle_hint")}</div>`}_renderOwnTariff(t){const e=t.goals||{},s=H`
            <div class="ge-title" style="margin-top:10px">
                <ha-icon icon="mdi:cash-multiple" style="--mdc-icon-size:14px;color:#488fc2"></ha-icon>
                ${this._t("device_tariff_section")}
            </div>`;if(String(t.id||"").startsWith("heat_pump"))return H`${s}<div class="ge-hint">${this._t("device_tariff_heat_pump")}</div>`;const i=(e,s)=>{t.goals={...t.goals||{},[e]:s},this._sendDeviceUpdate(t.id,e,String(s))},r=(t,s,r)=>this.hass&&customElements.get("ha-entity-picker")?H`
            <ha-entity-picker class="ge-entity"
                   .hass=${this.hass}
                   .value=${e[t]||""}
                   .includeDomains=${s}
                   .entityFilter=${r?t=>t?.attributes?.device_class===r:void 0}
                   allow-custom-entity
                   @value-changed=${e=>i(t,e.detail?.value??"")}
                   @click=${t=>t.stopPropagation()}></ha-entity-picker>
            `:H`
            <input type="text" class="ge-entity" .value="${e[t]||""}"
                   @change=${e=>i(t,e.target.value.trim())}
                   @click=${t=>t.stopPropagation()}>`,a=parseFloat(e.tariff_rate)||0;return H`
            ${s}
            <div class="ge-row">
                <span class="ge-label">${this._t("device_tariff_rate")}</span>
                <span class="ge-ctl">
                    <input type="number" min="0" step="0.001" style="width:72px"
                           .value="${a>0?String(a):""}" placeholder="\u2014"
                           @change=${t=>{const e=parseFloat(t.target.value);i("tariff_rate",Number.isFinite(e)&&e>0?e:0)}}
                           @click=${t=>t.stopPropagation()}>
                    <span class="ge-unit">/kWh</span>
                </span>
            </div>
            <div class="ge-row">
                <span class="ge-label">${this._t("device_tariff_entity")}</span>
                <span class="ge-ctl">${r("tariff_entity",["sensor","input_number"],null)}</span>
            </div>
            <div class="ge-row">
                <span class="ge-label">${this._t("device_tariff_meter")}</span>
                <span class="ge-ctl">${r("tariff_meter",["sensor"],"energy")}</span>
            </div>
            <div class="ge-hint">${this._t("device_tariff_hint")}</div>`}_dragStart(t,e){const s=this.devices.find(t=>t.id===e);if(!s||s.dependsOn&&s.dependsOn.length)return;if(null!=t.button&&0!==t.button)return;t.preventDefault();const i=t.currentTarget,r=i.closest(".device"),a=this.renderRoot.getElementById("device-list");if(!r||!a)return;const n=Array.from(a.querySelectorAll(".device")),o=n.map(t=>{const e=t.getBoundingClientRect();return e.top+e.height/2});this._interacting=!0;const l=n.indexOf(r);this._drag={id:e,handle:i,row:r,rows:n,centres:o,pointerY0:t.clientY,fromIndex:l,dropIndex:l,pointerId:t.pointerId},r.classList.add("dragging-row");try{i.setPointerCapture(t.pointerId)}catch(t){}this._dragMoveBound=this._dragMoveBound||this._dragMove.bind(this),this._dragEndBound=this._dragEndBound||this._dragEnd.bind(this),window.addEventListener("pointermove",this._dragMoveBound),window.addEventListener("pointerup",this._dragEndBound),window.addEventListener("pointercancel",this._dragEndBound)}_dragMove(t){const e=this._drag;if(!e)return;t.preventDefault(),e.row.style.transform=`translateY(${t.clientY-e.pointerY0}px)`;const s=function(t,e,s){let i=0;for(let r=0;r<t.length;r++)r!==e&&s>t[r]&&i++;return i}(e.centres,e.fromIndex,t.clientY);s!==e.dropIndex&&(e.dropIndex=s,this._paintDropLine(e,s))}_paintDropLine(t,e){t.rows.forEach(t=>t.classList.remove("drop-above","drop-below"));const s=t.rows[e<t.fromIndex?e:e+1];s&&s!==t.row?s.classList.add("drop-above"):t.rows[t.rows.length-1]?.classList.add("drop-below")}_dragEnd(t){const e=this._drag;if(e){window.removeEventListener("pointermove",this._dragMoveBound),window.removeEventListener("pointerup",this._dragEndBound),window.removeEventListener("pointercancel",this._dragEndBound);try{e.handle.releasePointerCapture(e.pointerId)}catch(t){}e.row.style.transform="",e.row.classList.remove("dragging-row"),e.rows.forEach(t=>t.classList.remove("drop-above","drop-below")),this._interacting=!1,this._drag=null,"pointercancel"!==t.type&&e.dropIndex!==e.fromIndex&&this._moveDeviceToIndex(e.id,e.dropIndex)}}_moveDeviceToIndex(t,e){this.devices=function(t,e,s){const i=t.slice(),r=i.findIndex(t=>t.id===e);if(-1===r)return i;const[a]=i.splice(r,1),n=Math.max(0,Math.min(s,i.length));return i.splice(n,0,a),function(t){return t.forEach((t,e)=>{t.priority=e+1}),t}($r(i))}(this.devices,t,e),this.requestUpdate(),this._sendPriorityUpdate()}_bindEvents(){const t=t=>{const e=t.target.closest("[data-action]");if(!e)return;const s=e.dataset.action,i=e.dataset.device;if("controllable"===s){const t=this.devices.find(t=>t.id===i);t&&(t.isControllable=!t.isControllable,this._sendDeviceUpdate(i,"controllable",t.isControllable),this.requestUpdate())}else if("move-up"===s||"move-down"===s)this._moveDevice(i,"move-up"===s?-1:1);else if("configure"===s)this._showConfigureModal(i,e.dataset.name);else if("toggle-help"===s)this._showHelp=!this._showHelp,this.requestUpdate();else if("toggle-goal"===s)this._goalOpen[i]=!this._goalOpen[i],this.requestUpdate();else if("set-overnight"===s){const t=this.devices.find(t=>t.id===i);t&&this._setOvernightSource(t,e.dataset.overnight)}},e=t=>{const e=t.target.closest('[data-action="combined_mode"]');if(e){const t=e.dataset.device,s=this.devices.find(e=>e.id===t);return void(s&&this._applyMergedMode(s,e.value))}const s=t.target.closest("[data-goal]");if(s){const t=s.dataset.device,e=s.dataset.goal;let i=s.value;const r=this.devices.find(e=>e.id===t);return r&&(r.goals=r.goals||{},r.goals[e]=i),void this._sendDeviceUpdate(t,e,String(i))}const i=t.target.closest('[data-action="depends_on"]');if(i){const t=i.dataset.device,e=this.devices.find(e=>e.id===t);if(e){const s=i.value;e.dependsOn=s?[s]:[],this._sendDeviceUpdate(t,"depends_on",s),this._regroupChildren(),this.devices.forEach((t,e)=>{t.priority=e+1}),this.requestUpdate(),this._sendPriorityUpdate()}}},s=this.renderRoot.querySelector("ha-card");s&&!s._semEvtBound&&(s._semEvtBound=!0,s.addEventListener("click",t),s.addEventListener("change",e))}_moveDevice(t,e){const s=this.devices.findIndex(e=>e.id===t);if(-1===s)return;const i=s+e;i<0||i>=this.devices.length||this.devices[s].dependsOn.length||this._moveDeviceToIndex(t,i)}_getDependencyDepth(t){let e=0,s=t;const i=new Set;for(;s.dependsOn.length>0&&e<5;){i.add(s.id);const t=s.dependsOn[0];if(i.has(t))break;const r=this.devices.find(e=>e.id===t);if(!r)break;e++,s=r}return e}_regroupChildren(){this.devices=$r(this.devices)}_showServiceError(t){const e=t&&t.message?String(t.message):String(t||"");this._serviceError=e,this.requestUpdate(),clearTimeout(this._serviceErrorTimer),this._serviceErrorTimer=setTimeout(()=>{this._serviceError="",this.requestUpdate()},12e3)}_sendPriorityUpdate(){this._hass&&(this._hass.callService("solar_energy_management","update_device_priorities",{priorities:this.devices.map(t=>({device_id:t.id,priority:t.priority}))}).catch(t=>this._showServiceError(t)),this._priorityFrozenUntil=Date.now()+15e3)}_sendDeviceUpdate(t,e,s){this._hass&&this._hass.callService("solar_energy_management","update_device_config",{device_id:t,property:e,value:s}).catch(t=>this._showServiceError(t))}_sendTargetPeakUpdate(t,e=!1,s=null){this._hass&&this._hass.callService("solar_energy_management","update_target_peak",{target_peak_limit:t,peak_limit_unlimited:e}).catch(t=>{s&&this._peakHold===s&&(this._peakHold=null),this._lastReads=null,this._showServiceError(t)})}async _ensureEntityPicker(){if(!customElements.get("ha-entity-picker"))try{const t=await(window.loadCardHelpers?.());if(t?.createCardElement){const e=await t.createCardElement({type:"entities",entities:[]});await(e.constructor?.getConfigElement?.())}}catch(t){}}async _showConfigureModal(t,e){const s=this.renderRoot.getElementById("sem-config-modal");s&&s.remove();const i=function(t,e){return(t||[]).find(t=>t.id===e)||null}(this.devices,t),r=i?.energySensor||"",a=function(t){const e=t||{};return{type:wr.includes(e.type)?e.type:"switch",entity:e.entity||"",service:e.service||"",param:e.param||"current",shed_value:null!=e.shed_value?e.shed_value:0,restore_value:null!=e.restore_value?e.restore_value:16}}(i?.control),n="manual_mapping"===i?.control?.discovered_via;await this._ensureEntityPicker();const o=document.createElement("div");o.id="sem-config-modal",o.style.cssText="position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:999;display:flex;align-items:center;justify-content:center";const l=i&&!["ev_charger","ev_charging","battery"].includes(i.deviceType);o.innerHTML=function({deviceName:t,values:e,t:s,hasManual:i=!1,behindRelay:r=null,inUse:a=""}){const n=e,o="service"===n.type,l=(t,e)=>`<option value="${t}" ${n.type===t?"selected":""}>${e}</option>`;return`\n        <div style="background:var(--card-background-color,#1e1e2e);border-radius:12px;padding:24px;min-width:320px;max-width:90vw;color:var(--primary-text-color,#e0e0e0)">\n            <div style="font-weight:700;margin-bottom:16px">${s("configure_device")}: ${Sr(t)}</div>\n            ${a?`<div class="cfg-in-use" style="font-size:13px;opacity:0.8;margin-bottom:12px">${Sr(s("cfg_in_use_hint").replace(/\{entity\}/g,a))}</div>`:""}\n            <label style="font-size:13px;opacity:0.7">${s("control_type")}</label>\n            <select id="cfg-type" style="${Cr}">\n                ${l("switch",s("mode_switch"))}\n                ${l("current",s("mode_current"))}\n                ${l("input_boolean",s("mode_input_boolean"))}\n                ${l("service",s("mode_service"))}\n            </select>\n            <div id="cfg-entity-group" style="display:${o?"none":"block"}">\n                <label style="font-size:13px;opacity:0.7">${s("control_entity")}</label>\n                <input id="cfg-entity" type="text" placeholder="switch.example" value="${Sr(n.entity)}" style="${Cr}">\n            </div>\n            <div id="cfg-service-group" style="display:${o?"block":"none"}">\n                <label style="font-size:13px;opacity:0.7">${s("svc_service")}</label>\n                <input id="cfg-service" type="text" placeholder="keba.set_current" value="${Sr(n.service)}" style="${Cr}">\n                <label style="font-size:13px;opacity:0.7">${s("svc_param")}</label>\n                <input id="cfg-param" type="text" placeholder="current" value="${Sr(n.param)}" style="${Cr}">\n                <div style="display:flex;gap:8px">\n                    <div style="flex:1">\n                        <label style="font-size:13px;opacity:0.7">${s("svc_shed_value")}</label>\n                        <input id="cfg-shed" type="number" value="${Sr(n.shed_value)}" style="${Cr}">\n                    </div>\n                    <div style="flex:1">\n                        <label style="font-size:13px;opacity:0.7">${s("svc_restore_value")}</label>\n                        <input id="cfg-restore" type="number" value="${Sr(n.restore_value)}" style="${Cr}">\n                    </div>\n                </div>\n            </div>\n            ${null===r?"":`\n            <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin:4px 0 2px">\n                <span style="font-size:14px">${s("cfg_behind_operator_relay")}</span>\n                <span id="cfg-relay" role="switch" aria-checked="${r?"true":"false"}" class="${r?"on":""}"\n                      style="cursor:pointer"></span>\n            </div>\n            <div style="font-size:12px;opacity:.65;font-style:italic;margin:0 0 12px;max-width:340px">${s("cfg_help_behind_operator_relay")}</div>\n            <style>\n                #cfg-relay { width:36px;height:20px;border-radius:10px;background:rgba(127,127,127,.45);position:relative;display:inline-block;flex:none;transition:background .15s }\n                #cfg-relay::after { content:'';position:absolute;left:2px;top:2px;width:16px;height:16px;border-radius:50%;background:#fff;transition:left .15s }\n                #cfg-relay.on { background:#4caf50 }\n                #cfg-relay.on::after { left:18px }\n            </style>`}\n            <div class="cfg-error" style="color:#f44336;font-size:13px;margin:4px 0 8px;display:none"></div>\n            <div style="display:flex;gap:8px;align-items:center">\n                ${i?`<button id="cfg-remove" style="padding:8px 12px;border-radius:6px;border:none;cursor:pointer;background:transparent;color:#f44336">${s("clear_mapping")}</button>`:""}\n                <div style="flex:1"></div>\n                <button id="cfg-cancel" style="padding:8px 16px;border-radius:6px;border:none;cursor:pointer;background:rgba(255,255,255,0.1);color:inherit">${s("cancel")}</button>\n                <button id="cfg-save" style="padding:8px 16px;border-radius:6px;border:none;cursor:pointer;background:#4caf50;color:white">${s("save")}</button>\n            </div>\n        </div>`}({deviceName:e,values:a,t:t=>this._t(t),hasManual:n,behindRelay:l?!!i.behindRelay:null,inUse:n||a.entity?"":i?.controlEntity||""}),this.renderRoot.appendChild(o);const c=o.querySelector("#cfg-type"),d=o.querySelector("#cfg-entity-group"),p=o.querySelector("#cfg-service-group"),_=o.querySelector("#cfg-entity"),h=o.querySelector(".cfg-error"),u=t=>{h.textContent=t,h.style.display="block"};let g=null;customElements.get("ha-entity-picker")&&(g=document.createElement("ha-entity-picker"),g.hass=this._hass,g.allowCustomEntity=!0,g.value=_.value,g.includeDomains=kr[c.value],g.style.cssText="display:block;margin:6px 0 12px",g.addEventListener("value-changed",t=>{_.value=t.detail.value||""}),_.style.display="none",_.parentNode.insertBefore(g,_));c.addEventListener("change",()=>{const t="service"===c.value;d.style.display=t?"none":"block",p.style.display=t?"block":"none",g&&!t&&(g.includeDomains=kr[c.value])});const m=o.querySelector("#cfg-relay");m&&i&&m.addEventListener("click",()=>{const t=!m.classList.contains("on");m.classList.toggle("on",t),m.setAttribute("aria-checked",String(t)),i.behindRelay=t,this._sendDeviceUpdate(i.id,"behind_operator_relay",String(t))}),o.addEventListener("click",t=>{t.target===o&&o.remove()}),o.querySelector("#cfg-cancel").addEventListener("click",()=>o.remove());const f=o.querySelector("#cfg-remove");f&&f.addEventListener("click",()=>{this._hass.callService("solar_energy_management","remove_device_control_mapping",{energy_sensor:r}).then(()=>{i&&(i.control=null,this.requestUpdate()),o.remove()}).catch(t=>u(t.message))}),o.querySelector("#cfg-save").addEventListener("click",()=>{const t=function(t){const e=e=>t.querySelector("#"+e);return{type:e("cfg-type")?.value||"switch",entity:(e("cfg-entity")?.value||"").trim(),service:(e("cfg-service")?.value||"").trim(),param:(e("cfg-param")?.value||"").trim()||"current",shed_value:e("cfg-shed")?.value,restore_value:e("cfg-restore")?.value}}(o);let e;g&&(t.entity=(g.value||"").trim());try{e=function(t,e){const s=wr.includes(e.type)?e.type:"switch";if("service"===s){if(!e.service)throw new Error("mapping_service_required");return{energy_sensor:t,control_type:"service",service:e.service,param:e.param||"current",shed_value:Number(e.shed_value),restore_value:Number(e.restore_value)}}if(!e.entity)throw new Error("mapping_entity_required");return{energy_sensor:t,control_type:s,control_entity:e.entity}}(r,t)}catch(t){return void u(this._t(t.message))}this._hass.callService("solar_energy_management","set_device_control_mapping",e).then(()=>{i&&(i.control="service"===e.control_type?{type:"service",service:e.service,param:e.param,shed_value:e.shed_value,restore_value:e.restore_value,discovered_via:"manual_mapping"}:{type:e.control_type,entity:e.control_entity,discovered_via:"manual_mapping"},this.requestUpdate()),o.remove()}).catch(t=>u(t.message))})}_getPeakColor(){if(this.peakLimitUnlimited)return"#4caf50";if(null==this.currentPeak)return"#888";const t=this.targetPeakLimit>0?this.currentPeak/this.targetPeakLimit*100:0;return t>=100?"#f44336":t>=90?"#ff9800":t>=70?"#2196f3":"#4caf50"}_resolveDeviceIcon(t){for(const e of[t.switch_entity,t.power_entity,t.control?.entity])if(e){const t=this._hass?.states[e];if(t?.attributes?.icon)return t.attributes.icon}return{ev_charger:"mdi:ev-station",ev_charging:"mdi:ev-station",battery:"mdi:home-battery",heating:"mdi:radiator",heat_pump:"mdi:heat-pump",water_heater:"mdi:water-boiler",hot_water:"mdi:water-boiler",pool_pump:"mdi:pool",appliance:"mdi:washing-machine",climate:"mdi:thermostat",light:"mdi:lightbulb",printer:"mdi:printer",computer:"mdi:desktop-classic",network:"mdi:network",fan:"mdi:fan",dryer:"mdi:tumble-dryer",dishwasher:"mdi:dishwasher",freezer:"mdi:fridge",refrigerator:"mdi:fridge"}[t.device_type]||"mdi:power-plug"}getCardSize(){return Math.max(5,3+this.devices.length)}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"sem-load-priority-card",name:"SEM Load Priority Card",description:"Drag and drop interface for managing load shedding priorities",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-load-priority-card",preview:!0});const Er=[{id:"surplus",icon:"mdi:solar-power",color:"#ff9800",titleKey:"surplus_control",subtitleFn:t=>{const e=Tt(t._valNum("surplus_active_devices"),0),s=Tt(t._valNum("surplus_total_devices"),0),i=Tt(t._valNum("surplus_allocated_w"),0);return`${e}/${s} ${t._t("devices")} · ${i}W`}},{id:"battery",icon:"mdi:battery-medium",color:"#4db6ac",titleKey:"battery_management",subtitleFn:t=>{const e=It(t._valNum("battery_soc",null)).label,s=t._val("battery_status")||"";return`SOC ${e} · ${s?t._t(s.toLowerCase()):"—"}`}},{id:"hotwater",icon:"mdi:water-thermometer",color:"#f06292",titleKey:"hot_water_title",subtitleFn:()=>""},{id:"heatpump",icon:"mdi:heat-pump",color:"#4db6ac",titleKey:"heat_pump_title",subtitleFn:t=>{if(!t._bin("heat_pump_registered"))return"";const e=t._val("heat_pump_sg_ready_state");return e?`${t._valLabel("heat_pump_mode")||"—"} · SG-Ready ${e}`:""}},{id:"tariff",icon:"mdi:cash-multiple",color:"#96CAEE",titleKey:"tariff_pricing",subtitleFn:t=>{const e=t._valLabel("tariff_provider")||"—",s=t._val("tariff_price_level")||"";return s?`${e} · ${t._t(ke(s))}`:e}},{id:"peak",icon:"mdi:flash-alert",color:"#ff9800",titleKey:"peak_load_management",subtitleFn:t=>{const e=Tt(t._valNum("consecutive_peak_15min"),1),s=Tt(t._valNum("monthly_consecutive_peak"),1);return`${t._t("peak")} ${e} kW · ${t._t("monthly_peak")} ${s} kW`}}],Nr=["sensor.sem_surplus_active_devices","sensor.sem_surplus_total_devices","sensor.sem_surplus_allocated_w","sensor.sem_surplus_total_w","sensor.sem_surplus_distributable_w","sensor.sem_surplus_unallocated_w","sensor.sem_battery_soc","sensor.sem_battery_status","sensor.sem_diag_battery_capacity","number.sem_legionella_target_temp","binary_sensor.sem_heat_pump_registered","sensor.sem_heat_pump_sg_ready_state","sensor.sem_heat_pump_mode","binary_sensor.sem_heat_pump_solar_boost","sensor.sem_tariff_provider","sensor.sem_tariff_price_level","sensor.sem_tariff_current_import_rate","sensor.sem_consecutive_peak_15min","sensor.sem_monthly_consecutive_peak","sensor.sem_current_vs_peak_percentage","sensor.sem_load_management_status","sensor.sem_load_management_recommendation","sensor.sem_peak_margin","sensor.sem_available_load_reduction","sensor.sem_controllable_devices_count","switch.sem_observer_mode","sensor.sem_target_peak_limit","sensor.sem_diag_grid_sign"],Fr={"sensor.sem_target_peak_limit":["peak_limit_unlimited"],"sensor.sem_load_management_status":["shed_signal_active","shed_signal_cap_kw","shed_signal_since"]};kt("sem-control-card",class extends Lt{static get watchedEntities(){return Nr}static get watchedAttributes(){return Fr}static get properties(){return{...super.properties}}constructor(){super(),this._collapsed={surplus:!0,battery:!1,hotwater:!0,heatpump:!0,tariff:!1,peak:!0}}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||"sensor.sem_"}_val(t){const e=this._hass?.states[`${this._prefix}${t}`];return e&&"unavailable"!==e.state&&"unknown"!==e.state?e.state:""}_valNum(t,e=null){return At(this._hass?.states[`${this._prefix}${t}`])??e}_numVal(t,e=null){return At(this._hass?.states[`number.sem_${t}`])??e}_switchOn(t){return"on"===this._hass?.states[`switch.sem_${t}`]?.state}_bin(t){return"on"===this._hass?.states[`binary_sensor.sem_${t}`]?.state}_toggleSection(t){this._collapsed={...this._collapsed,[t]:!this._collapsed[t]},this.requestUpdate()}_renderStepper(t,e,s){const i=this._hass?.states[t];if(!i)return K;const r=this._frozenEntities[t],a=r?r.value:At(i),n=parseFloat(i.attributes.step)||1,o=i.attributes.unit_of_measurement||"",l=Tt(a,n<1?1:0)+(o?" "+o:"");return H`
            <div class="stepper-cell">
                <div class="stepper-row">
                    <span class="stepper-label">${this._t(e)}</span>
                    <div class="stepper-controls">
                        <button
                            class="stepper-minus" aria-label="Decrease"
                            @click=${()=>this._stepNumber(t,-1)}
                            @pointerdown=${()=>this._startHold(t,-1)}
                            @pointerup=${()=>this._stopHold(t)}
                            @pointerleave=${()=>this._stopHold(t)}
                        >−</button>
                        <span class="stepper-value">${l}</span>
                        <button
                            class="stepper-plus" aria-label="Increase"
                            @click=${()=>this._stepNumber(t,1)}
                            @pointerdown=${()=>this._startHold(t,1)}
                            @pointerup=${()=>this._stopHold(t)}
                            @pointerleave=${()=>this._stopHold(t)}
                        >+</button>
                    </div>
                </div>
            </div>
        `}_renderSelect(t,e,s){const i=this._hass?.states[t];if(!i)return K;const r=this._frozenEntities[t],a=r?r.value:i.state,n=i.attributes.options||[];return H`
            <div class="ctrl-row">
                <span class="ctrl-label">${this._t(e)}</span>
                <select
                    class="sem-select"
                    .value=${a}
                    @change=${e=>this._selectOption(t,e.target.value)}
                >
                    ${n.map(t=>H`<option value="${t}" ?selected=${t===a}>${t}</option>`)}
                </select>
            </div>
        `}_renderSurplusSection(t){const e=Tt(this._valNum("surplus_total_w"),0),s=Tt(this._valNum("surplus_distributable_w"),0),i=Tt(this._valNum("surplus_allocated_w"),0),r=Tt(this._valNum("surplus_unallocated_w"),0);return H`
            <div class="info-tiles">
                <div class="info-tile">
                    <ha-icon icon="mdi:solar-power" style="--mdc-icon-size:18px;color:#ff9800"></ha-icon>
                    <div class="info-tile-content">
                        <span class="info-tile-label">${this._t("surplus_available")}</span>
                        <span class="info-tile-values">
                            <span>${e}W</span>
                            <span class="info-tile-sep">·</span>
                            <span>${s}W</span>
                        </span>
                    </div>
                </div>
                <div class="info-tile">
                    <ha-icon icon="mdi:chart-pie" style="--mdc-icon-size:18px;color:#8DC892"></ha-icon>
                    <div class="info-tile-content">
                        <span class="info-tile-label">${this._t("surplus_allocation")}</span>
                        <span class="info-tile-values">
                            <span>${i}W</span>
                            <span class="info-tile-sep">·</span>
                            <span>${r}W</span>
                        </span>
                    </div>
                </div>
            </div>
        `}_renderBatterySection(t){const e=this._valNum("diag_battery_capacity"),s=e>0?e.toFixed(1)+" kWh":"—",i=this._valLabel("diag_grid_sign")||"—";return H`
            <div class="readonly-row">
                <span class="ctrl-label">${this._t("capacity_kwh")}</span>
                <span class="readonly-value">${s}</span>
            </div>
            <div class="readonly-row">
                <span class="ctrl-label">${this._t("grid_sign")}</span>
                <span class="readonly-value">${i}</span>
            </div>
        `}_renderHeatPumpSection(t){if(!this._bin("heat_pump_registered"))return H`<div class="info-box-text" style="opacity:0.6">
                ${this._t("heat_pump_not_configured")}
            </div>`;const e=this._val("heat_pump_sg_ready_state"),s=this._valLabel("heat_pump_mode")||"—",i=this._switchOn("heat_pump_solar_boost")?"#ff9800":"#4db6ac";return H`
            <div class="readonly-row">
                <ha-icon icon="mdi:heat-pump-outline" style="--mdc-icon-size:18px;color:${i}"></ha-icon>
                <span class="ctrl-label" style="flex:1">${this._t("heat_pump_mode")}</span>
                <span class="readonly-value">${s}</span>
            </div>
            <div class="readonly-row">
                <ha-icon icon="mdi:transmission-tower" style="--mdc-icon-size:18px;color:${i}"></ha-icon>
                <span class="ctrl-label" style="flex:1">${this._t("heat_pump_sg_ready_state")}</span>
                <span class="readonly-value">${e}</span>
            </div>
        `}_renderHotWaterSection(t){return H`
            ${this._renderStepper("number.sem_legionella_target_temp","legionella_target",t)}
            <div class="info-box">
                <ha-icon icon="mdi:shield-alert" style="--mdc-icon-size:16px;color:#ff9800"></ha-icon>
                <div>
                    <div class="info-box-title">${this._t("legionella_prevention")}</div>
                    <div class="info-box-text">
                        DE (DVGW W 551): ≥ 60°C · CH (SIA 385/1): ≥ 60°C · AT (ÖNORM B 5019): 60°C / 70°C 3 min
                    </div>
                </div>
            </div>
        `}_renderTariffSection(t){const e=this._hass?.states["sensor.sem_tariff_current_import_rate"],s=e?e.state:"—",i=e?.attributes?.unit_of_measurement||"";return H`
            <div class="readonly-row tariff-rate-row">
                <ha-icon icon="mdi:flash" style="--mdc-icon-size:18px;color:#ff9800"></ha-icon>
                <span class="ctrl-label" style="flex:1">${this._t("current_electricity_price")}</span>
                <span class="readonly-value tariff-rate-value">${s} ${i}</span>
            </div>
        `}_renderPeakSection(t){const e=this._valNum("current_vs_peak_percentage"),s=e>90?"#f44336":e>70?"#ff9800":"#8DC892",i=Tt(this._valNum("controllable_devices_count"),0),r=this._valNum("available_load_reduction"),a=Ht(this._hass?.states[`${this._prefix}target_peak_limit`]);return H`
            <div class="peak-hero">
                ${a?H`<span class="peak-pct" style="color:#8DC892">${this._t("uncapped")}</span>`:H`<span class="peak-pct" style="color:${s}">${Tt(e,0)}%</span>
                <span class="peak-of-limit">${this._t("of_limit")}</span>`}
            </div>
            <div class="peak-detail">
                <span class="peak-status">${this._valLabel("load_management_status")||"—"}</span>
                <span class="peak-sep">·</span>
                <span class="peak-rec">${(()=>{const t=this._val("load_management_recommendation");return t?this._t(t):""})()}</span>
            </div>
            <div class="info-tiles">
                <div class="info-tile">
                    <ha-icon icon="mdi:shield-check" style="--mdc-icon-size:18px;color:#8DC892"></ha-icon>
                    <div class="info-tile-content">
                        <span class="info-tile-label">${this._t("peak_margin")}</span>
                        <span class="info-tile-value">${a?this._t("uncapped"):`${Tt(this._valNum("peak_margin"),1)} kW`}</span>
                    </div>
                </div>
                <div class="info-tile">
                    <ha-icon icon="mdi:power-plug-off" style="--mdc-icon-size:18px;color:#ff9800"></ha-icon>
                    <div class="info-tile-content">
                        <span class="info-tile-label">${this._t("sheddable")}</span>
                        <span class="info-tile-value">${Tt(r,1)} kW · ${i} ${this._t("devices")}</span>
                    </div>
                </div>
            </div>
        `}_renderSectionHeader(t,e){const s=this._collapsed[t.id],i=s?"rotate(-90deg)":"rotate(0deg)";return H`
            <div
                class="section-header"
                tabindex="0"
                role="button"
                aria-expanded="${!s}"
                @click=${()=>this._toggleSection(t.id)}
                @keydown=${e=>{"Enter"!==e.key&&" "!==e.key||(e.preventDefault(),this._toggleSection(t.id))}}
            >
                <ha-icon icon="${t.icon}" style="--mdc-icon-size:20px;color:${t.color}"></ha-icon>
                <span class="section-title-text">${this._t(t.titleKey)}</span>
                <span class="section-subtitle">${t.subtitleFn(this)}</span>
                <ha-icon
                    class="chevron"
                    icon="mdi:chevron-down"
                    style="--mdc-icon-size:18px;transform:${i}"
                ></ha-icon>
            </div>
        `}_renderSection(t,e,s){const i=this._collapsed[t.id];return H`
            <div class="section ${i?"":"expanded"}"
                 style="--section-accent: ${t.color}">
                ${this._renderSectionHeader(t,s)}
                <div class="section-content ${i?"":"expanded"}">
                    <div class="section-body">
                        ${e(s)}
                    </div>
                </div>
            </div>
        `}render(){if(!this._config)return K;const t=this._theme(),e=!1!==t.isDark,s=t.accent||"#42a5f5",i=this._switchOn("observer_mode"),r=this._hass?.states?.["sensor.sem_load_management_status"]?.attributes||{},a=!0===r.shed_signal_active,n=a?this._operatorBanner(r):"",o={surplus:t=>this._renderSurplusSection(t),battery:t=>this._renderBatterySection(t),hotwater:t=>this._renderHotWaterSection(t),heatpump:t=>this._renderHeatPumpSection(t),tariff:t=>this._renderTariffSection(t),peak:t=>this._renderPeakSection(t)};return H`
            <style>
                :host { display: block; contain: layout style paint; }
                .wrap {
                    padding: 16px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 25%, rgba(150,202,238,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${t.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${t.text});
                }

                /* ── Observer warning ── */
                .observer-warning {
                    display: flex; align-items: center; gap: 10px;
                    border-radius: 12px;
                    background: radial-gradient(ellipse 60% 50% at 50% 40%, rgba(244,67,54,0.12) 0%, transparent 100%);
                    border: 1px solid rgba(244,67,54,0.35);
                    color: #f44336;
                    font-size: 13px; font-weight: 500;
                    overflow: hidden;
                    transition: max-height 0.3s ease, opacity 0.2s ease, margin-bottom 0.3s ease, padding 0.3s ease;
                    max-height: ${i?"60px":"0"};
                    opacity: ${i?"1":"0"};
                    margin-bottom: ${i?"12px":"0"};
                    padding: ${i?"12px 16px":"0 16px"};
                }

                /* ── (#1021) Grid operator's relay ── */
                .operator-banner {
                    display: flex; align-items: center; gap: 10px;
                    border-radius: 12px; margin-bottom: 12px; padding: 12px 16px;
                    background: rgba(255,152,0,0.08);
                    border: 1px solid #ff9800;
                    color: #ff9800;
                    font-size: 13px; font-weight: 500;
                }

                /* ── Sections (polish: color accent + EV-card-matching typography) ── */
                .section {
                    margin-bottom: 10px;
                    border-radius: 14px;
                    background: ${t.surface};
                    border: 1px solid ${t.surfaceBorder};
                    overflow: hidden;
                    transition: border-color 0.2s, box-shadow 0.2s;
                    position: relative;
                }
                /* When expanded: subtle color-coded accent stripe matching the
                   section icon's color, plus a soft glow that ties the card
                   together with the EV card's hint-row aesthetic. */
                .section.expanded {
                    border-color: color-mix(in srgb, var(--section-accent) 40%, ${t.surfaceBorder});
                    box-shadow: inset 3px 0 0 0 var(--section-accent);
                }
                .section:hover { border-color: ${e?"rgba(255,255,255,0.18)":"rgba(0,0,0,0.12)"}; }

                .section-header {
                    display: flex; align-items: center; gap: 10px;
                    padding: 13px 14px;
                    cursor: pointer;
                    user-select: none;
                    -webkit-user-select: none;
                    transition: background 0.15s;
                }
                .section-header:hover { background: ${t.surfaceHover}; }
                .section.expanded .section-header {
                    background: color-mix(in srgb, var(--section-accent) 6%, transparent);
                }
                .section-title-text {
                    font-size: 15px; font-weight: 600;
                    white-space: nowrap;
                    letter-spacing: 0.1px;
                }
                .section-subtitle {
                    flex: 1;
                    font-size: 13px;
                    color: var(--secondary-text-color, ${t.textSec});
                    text-align: right;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    margin-right: 4px;
                }
                .chevron {
                    transition: transform 0.25s ease;
                    color: var(--secondary-text-color, ${t.textSec});
                    flex-shrink: 0;
                }

                /* ── Collapsible content ── */
                .section-content {
                    max-height: 0;
                    opacity: 0;
                    overflow: hidden;
                    transition: max-height 0.3s ease, opacity 0.2s ease;
                }
                .section-content.expanded {
                    max-height: 1000px;
                    opacity: 1;
                }
                .section-body { padding: 0 14px 14px; }

                .stepper-cell { display: flex; flex-direction: column; }

                /* ── Select ── */
                .ctrl-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 8px 0;
                    border-bottom: 1px solid ${t.surfaceBorder};
                    margin-bottom: 4px;
                }
                .ctrl-label { font-size: 14px; font-weight: 500; }
                .sem-select {
                    background: ${t.surface};
                    border: 1px solid ${t.surfaceBorder};
                    border-radius: 8px;
                    color: var(--primary-text-color, ${t.text});
                    padding: 6px 10px;
                    font-size: 14px;
                    font-family: inherit;
                    cursor: pointer;
                    min-width: 120px;
                    outline: none;
                }
                .sem-select:focus { border-color: ${s}; }
                .sem-select option {
                    background: ${e?"#1e232d":"#fff"};
                    color: ${e?"#e0e0e0":"#333"};
                }

                /* ── Number stepper ── */
                .stepper-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 7px 0;
                }
                .stepper-label {
                    font-size: 14px; font-weight: 500;
                    flex: 1; min-width: 0;
                    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
                }
                .stepper-controls { display: flex; align-items: center; gap: 2px; flex-shrink: 0; }
                .stepper-minus, .stepper-plus {
                    width: 30px; height: 30px;
                    border-radius: 8px;
                    border: 1px solid ${t.surfaceBorder};
                    background: ${t.surface};
                    color: var(--primary-text-color, ${t.text});
                    font-size: 16px; font-weight: 600;
                    cursor: pointer;
                    display: flex; align-items: center; justify-content: center;
                    transition: background 0.15s, border-color 0.15s;
                    user-select: none; -webkit-user-select: none;
                    touch-action: manipulation;
                    padding: 0; line-height: 1;
                }
                .stepper-minus:hover, .stepper-plus:hover {
                    background: ${t.surfaceHover};
                    border-color: ${s};
                }
                .stepper-minus:active, .stepper-plus:active {
                    background: ${e?"rgba(255,255,255,0.15)":"rgba(0,0,0,0.08)"};
                }
                .stepper-value {
                    font-size: 14px; font-weight: 600;
                    min-width: 60px; text-align: center;
                    font-variant-numeric: tabular-nums;
                }
                .stepper-pair {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 0 16px;
                }
                @media (max-width: 480px) { .stepper-pair { grid-template-columns: 1fr; } }

                /* ── Read-only row ── */
                .readonly-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 7px 0;
                }
                .readonly-value {
                    font-size: 14px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                    color: var(--secondary-text-color, ${t.textSec});
                }
                .tariff-rate-row {
                    gap: 8px;
                    border-bottom: 1px solid ${t.surfaceBorder};
                    margin-bottom: 8px; padding-bottom: 10px;
                }
                .tariff-rate-value { font-size: 15px; font-weight: 700; color: ${t.text}; }

                /* ── Info tiles (surplus, peak) ── */
                .info-tiles {
                    display: grid; grid-template-columns: 1fr 1fr;
                    gap: 8px; margin: 8px 0;
                }
                .info-tile {
                    display: flex; align-items: flex-start; gap: 8px;
                    padding: 10px; border-radius: 10px;
                    background: ${e?"rgba(255,255,255,0.03)":"rgba(0,0,0,0.02)"};
                    border: 1px solid ${t.surfaceBorder};
                }
                .info-tile ha-icon { margin-top: 1px; flex-shrink: 0; }
                .info-tile-content { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
                .info-tile-label {
                    font-size: 11px; font-weight: 500; text-transform: uppercase;
                    color: var(--secondary-text-color, ${t.textSec});
                    letter-spacing: 0.3px;
                }
                .info-tile-values { font-size: 13px; font-weight: 600; display: flex; gap: 4px; flex-wrap: wrap; }
                .info-tile-value { font-size: 13px; font-weight: 600; }
                .info-tile-sep { color: var(--secondary-text-color, ${t.textSec}); }
                @media (max-width: 480px) { .info-tiles { grid-template-columns: 1fr; } }

                /* ── Info box (legionella) ── */
                .info-box {
                    display: flex; gap: 8px;
                    padding: 10px 12px; border-radius: 10px;
                    background: ${e?"rgba(255,152,0,0.06)":"rgba(255,152,0,0.05)"};
                    border: 1px solid rgba(255,152,0,0.2);
                    margin-top: 8px;
                }
                .info-box ha-icon { flex-shrink: 0; margin-top: 1px; }
                .info-box-title { font-size: 12px; font-weight: 600; margin-bottom: 2px; }
                .info-box-text {
                    font-size: 11px; line-height: 1.4;
                    color: var(--secondary-text-color, ${t.textSec});
                }

                /* ── Peak hero ── */
                .peak-hero {
                    display: flex; align-items: baseline; justify-content: center;
                    gap: 6px; padding: 4px 0;
                }
                .peak-pct { font-size: 28px; font-weight: 700; font-variant-numeric: tabular-nums; }
                .peak-of-limit {
                    font-size: 12px; font-weight: 500;
                    color: var(--secondary-text-color, ${t.textSec});
                    text-transform: uppercase;
                }
                .peak-detail {
                    text-align: center; padding: 0 0 8px;
                    font-size: 12px;
                    color: var(--secondary-text-color, ${t.textSec});
                }
                .peak-sep { margin: 0 4px; }
            </style>
            <div class="wrap">
                <div class="observer-warning">
                    <ha-icon icon="mdi:eye-outline" style="--mdc-icon-size:20px;color:#f44336"></ha-icon>
                    <span>${this._t("observer_mode_active")} — ${this._t("observer_mode_readonly")}</span>
                </div>
                ${a?H`
                <div class="operator-banner">
                    <ha-icon icon="mdi:transmission-tower-export" style="--mdc-icon-size:20px;color:#ff9800"></ha-icon>
                    <span>${n}</span>
                </div>`:K}
                ${Er.map(e=>this._renderSection(e,o[e.id],t))}
            </div>
        `}_operatorBanner(t){const e="number"==typeof t.shed_signal_cap_kw?t.shed_signal_cap_kw.toFixed(1):"?";let s="?";if(t.shed_signal_since){const e=new Date(t.shed_signal_since);isNaN(e)||(s=e.toLocaleTimeString(this._hass?.language||void 0,{hour:"2-digit",minute:"2-digit"}))}return this._t("operator_limit_banner").replace("{kw}",e).replace("{time}",s)}getCardSize(){return 12}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"sem-control-card",name:"SEM Control Card",description:"Live controls — peak management, load shedding, heat pump SG-Ready, observer mode",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-control-card",preview:!1});class Ar extends ct{static get properties(){return{hass:{type:Object},entryId:{type:String,attribute:"entry-id"},optionKey:{type:String,attribute:"option-key"},chargerIndex:{type:Number,attribute:"charger-index"},chargerKey:{type:String,attribute:"charger-key"},domain:{type:String},includeDeviceClass:{type:String,attribute:"include-device-class"},label:{type:String},_saving:{state:!0},_error:{state:!0}}}constructor(){super(),this.entryId="",this.optionKey="",this.chargerIndex=-1,this.chargerKey="",this.domain="",this.includeDeviceClass="",this.label="",this._saving=!1,this._error=""}static get styles(){return a`
            :host { display: block; padding: 6px 0; }
            .picker-row { display: flex; align-items: center; gap: 8px; }
            .picker-label {
                font-size: 14px; font-weight: 500;
                color: var(--primary-text-color);
                min-width: 140px; flex-shrink: 0;
            }
            ha-entity-picker { flex: 1; min-width: 0; }
            .status {
                font-size: 11px; color: var(--secondary-text-color);
                margin-top: 3px;
            }
            .status.error { color: var(--error-color, #d33); }
            .status.ok { color: var(--success-color, #8DC892); }
        `}_entry(){return this.hass&&this.entryId&&(this.hass.config_entries||[]).find(t=>t.entry_id===this.entryId)||null}_currentValue(){const t=this._entry();if(!t||!t.options)return"";if(this.chargerKey&&this.chargerIndex>=0){const e=t.options.ev_chargers||[];return e[this.chargerIndex]?.[this.chargerKey]||""}return t.options[this.optionKey]||""}async _onChange(t){const e=t.detail?.value||"",s=this._entry();if(!s)return void(this._error="config entry not found");let i;if(this._saving=!0,this._error="",this.chargerKey&&this.chargerIndex>=0){const t=(s.options?.ev_chargers||[]).map(t=>({...t}));t[this.chargerIndex]||(t[this.chargerIndex]={}),t[this.chargerIndex][this.chargerKey]=e,i={...s.options,ev_chargers:t}}else i={...s.options,[this.optionKey]:e};try{await this.hass.callWS({type:"config_entries/update",entry_id:this.entryId,options:i}),this._saving=!1}catch(t){this._saving=!1,this._error=t?.message||String(t),console.error("[sem-entity-picker] save failed",t)}}render(){if(!this.hass)return K;const t=this._currentValue();return this.domain&&this.domain,this.includeDeviceClass&&this.includeDeviceClass,H`
            <div class="picker-row">
                ${this.label?H`<span class="picker-label">${this.label}</span>`:K}
                <ha-entity-picker
                    .hass=${this.hass}
                    .value=${t}
                    .includeDomains=${this.domain?[this.domain]:void 0}
                    .includeDeviceClasses=${this.includeDeviceClass?[this.includeDeviceClass]:void 0}
                    .allowCustomEntity=${!1}
                    @value-changed=${this._onChange}>
                </ha-entity-picker>
            </div>
            ${this._error?H`<div class="status error">⚠ ${this._error}</div>`:this._saving?H`<div class="status">saving…</div>`:K}
        `}}customElements.get("sem-entity-picker")||customElements.define("sem-entity-picker",Ar);const Tr=new Set(["w","kw","mw"]);function Ir(t){const e=t&&t.attributes||{};if(e.device_class)return"power"===e.device_class;const s=String(e.unit_of_measurement||"").trim().toLowerCase();return Tr.has(s)}const Rr=new Set(["gco2eq/kwh","gco2e/kwh","gco2/kwh","kgco2eq/kwh","kgco2e/kwh","kgco2/kwh","gco2eq/mwh","kgco2eq/mwh","kgco2/mwh","tco2/mwh","tco2eq/mwh"]);function Br(t){const e=t&&t.attributes||{},s=String(e.unit_of_measurement||"").toLowerCase().replace(/\s+/g,"").replace(/\u2082/g,"2");return Rr.has(s)}function Or(t){const e=String(t&&t.entity_id||"");if(e.startsWith("weather."))return!e.startsWith("weather.forecast_");const s=t&&t.attributes||{},i=String(s.unit_of_measurement||"").trim().toLowerCase();return"temperature"===s.device_class||"°c"===i||"°f"===i}function Lr(t){const e=t&&t.suggested_charger,s=t&&t.missing||[];return e&&e.id&&0===s.length?"add":function(t){const e=t&&t.suggested_charger;if(e&&e.id)return!1;const s=t&&t.missing||[],i=t&&t.charger_roles||[];return 1===s.length&&"control"===s[0]&&i.length>0}(t)?"watch":"report"}function Pr(t,e,s){if(!t||!t.config_key||!e)return null;if(!t.pair)return{[t.config_key]:e};const i=t.pair[e];if(!i||!Object.keys(i).length)return null;const r={[t.config_key]:e};for(const[a,n]of Object.entries(i)){if(a===t.config_key)return null;const i=(n||[]).filter(t=>t&&t!==e),o=s&&s[a],l=i.includes(o)?o:i[0];if(!l)return null;r[a]=l}return r}function Ur(t,e){return!!t&&Object.entries(t).every(([t,s])=>!!e&&e[t]===s)}const Wr=new Set(["ev_connected_sensor","ev_charging_sensor","ev_charging_power_sensor","ev_current_control_entity","ev_start_stop_entity","ev_charge_mode_entity","ev_current_sensor","ev_session_energy_sensor","ev_total_energy_sensor","ev_charger_service_entity_id"]);function Hr(t,e){return(t&&t.ev_charger_refs||[]).find(t=>t&&t.id===e)||null}function jr(t){if(!t)return null;const e=t.state;if(null==e||""===e||"unavailable"===e||"unknown"===e)return null;const s=parseFloat(e);if(Number.isNaN(s))return null;return"kw"===String((t.attributes||{}).unit_of_measurement||"").toLowerCase()?1e3*s:s}function Gr(t,e){return null===t&&null===e?null:(t||0)-(e||0)}const Kr=new Set(["overview","tariff","ev_chargers","battery_zones","sensor_sources"]),qr=new Set(["tariff_mode","electricity_import_rate","electricity_export_rate","dynamic_tariff_entity","tariff_schedule_entity","electricity_off_peak_rate","battery_discharge_protection_enabled","load_management_enabled","target_peak_limit"]),Vr={shed_signal_entity:"shed_signal_entity",shed_signal_limit:"shed_signal_entity"},Yr={electricity_off_peak_rate:"calendar"},Zr=new Set(["ev_charging_power_sensor","ev_current_control_entity"]),Xr=[{id:"basics",titleKey:"config_group_basics",sections:["overview","tariff","ev_chargers","battery_zones","sensor_sources"]},{id:"devices",titleKey:"config_group_devices",sections:["heat_pump","hot_water","load_management","pv_strings","detected_hardware"]},{id:"finetuning",titleKey:"config_group_finetuning",folds:!0,sections:["battery_scheduler","battery_intelligence","forecast","notifications","advanced"]}],Jr="pending:",Qr=[{id:"overview",icon:"mdi:check-decagram",color:"#8DC892",docs:"https://github.com/traktore-org/sem-community/blob/develop/docs/README.md",titleKey:"config_section_overview",subtitleFn:t=>t._overviewSubtitle(),expanded:!0},{id:"sensor_sources",docs:"https://github.com/traktore-org/sem-community/blob/develop/docs/SETUP_GUIDE.md#sensor-source-overrides",icon:"mdi:transmission-tower",color:"#488fc2",titleKey:"config_section_sensor_sources",subtitleFn:t=>t._sensorSourcesSubtitle()},{id:"detected_hardware",docs:"https://github.com/traktore-org/sem-community/blob/develop/docs/SUPPORTED_HARDWARE.md",icon:"mdi:radar",color:"#8DC892",titleKey:"config_section_detected_hardware",subtitleFn:t=>t._detectedHardwareSubtitle()},{id:"ev_chargers",docs:"https://github.com/traktore-org/sem-community/blob/develop/docs/EV_CHARGING_LOGIC.md#the-five-charge-modes",icon:"mdi:ev-station",color:"#5BC8D8",titleKey:"config_section_ev_chargers",subtitleFn:t=>t._evChargersSubtitle()},{id:"battery_zones",docs:"https://github.com/traktore-org/sem-community/blob/develop/docs/SETUP_GUIDE.md#6-soc-zone-strategy",icon:"mdi:battery-charging-medium",color:"#4db6ac",titleKey:"config_section_battery_zones",subtitleFn:t=>t._batteryZonesSubtitle()},{id:"tariff",docs:"https://github.com/traktore-org/sem-community/blob/develop/docs/SETUP_GUIDE.md#tariff-and-pricing-settings",icon:"mdi:cash-multiple",color:"#96CAEE",titleKey:"config_section_tariff",subtitleFn:t=>t._tariffSubtitle()},{id:"heat_pump",docs:"https://github.com/traktore-org/sem-community/blob/develop/docs/SETUP_GUIDE.md#10-heat-pump-and-hot-water",icon:"mdi:heat-pump",color:"#4db6ac",titleKey:"config_section_heat_pump",subtitleFn:t=>t._heatPumpSubtitle()},{id:"hot_water",docs:"https://github.com/traktore-org/sem-community/blob/develop/docs/SETUP_GUIDE.md#hot-water-boiler-separate-from-heat-pump",icon:"mdi:water-boiler",color:"#5BC8D8",titleKey:"config_section_hot_water",subtitleFn:t=>t._hotWaterSubtitle()},{id:"battery_scheduler",docs:"https://github.com/traktore-org/sem-community/blob/develop/docs/SETUP_GUIDE.md#9-battery-charge-scheduler",icon:"mdi:calendar-clock",color:"#f06292",titleKey:"config_section_battery_scheduler",subtitleFn:()=>""},{id:"battery_intelligence",docs:"https://github.com/traktore-org/sem-community/blob/develop/docs/USER_GUIDE.md#forecast-led-spending-v21",titleKey:"config_section_battery_intelligence",subtitleFn:t=>t._batteryIntelligenceSubtitle()},{id:"load_management",docs:"https://github.com/traktore-org/sem-community/blob/develop/docs/USER_GUIDE.md#load-management-settings",icon:"mdi:flash-alert",color:"#ff9800",titleKey:"config_section_load_management",subtitleFn:t=>t._loadMgmtSubtitle()},{id:"forecast",docs:"https://github.com/traktore-org/sem-community/blob/develop/docs/SETUP_GUIDE.md#forecast-settings",icon:"mdi:weather-partly-cloudy",color:"#ff9800",titleKey:"config_section_forecast",subtitleFn:t=>t._forecastSubtitle()},{id:"pv_strings",docs:"https://github.com/traktore-org/sem-community/blob/develop/docs/PV_STRINGS.md#what-you-get",icon:"mdi:solar-panel",color:"#ff9800",titleKey:"config_section_pv_strings",subtitleFn:t=>t._pvStringsSubtitle()},{id:"notifications",docs:"https://github.com/traktore-org/sem-community/blob/develop/docs/SETUP_GUIDE.md#notification-settings",icon:"mdi:bell-outline",color:"#96CAEE",titleKey:"config_section_notifications",subtitleFn:()=>""},{id:"advanced",docs:"https://github.com/traktore-org/sem-community/blob/develop/docs/SETUP_GUIDE.md#advanced-settings",icon:"mdi:cog-outline",color:"#888",titleKey:"config_section_advanced",subtitleFn:()=>""}],ta=["binary_sensor.sem_heat_pump_registered","sensor.sem_heat_pump_mode","sensor.sem_heat_pump_sg_ready_state","number.sem_heat_pump_boost_offset","sensor.sem_tariff_provider","sensor.sem_tariff_price_level","sensor.sem_tariff_current_import_rate","sensor.sem_forecast_source","sensor.sem_load_management_status","sensor.sem_battery_soc","sensor.sem_battery_status","number.sem_battery_priority_soc","number.sem_battery_buffer_soc","number.sem_battery_auto_start_soc","number.sem_battery_assist_min_surplus","number.sem_battery_assist_max_power","switch.sem_export_guard_enabled","switch.sem_export_guard_override_external","switch.sem_battery_house_sink_enabled","switch.sem_ev_morning_window_enabled","number.sem_export_guard_engage_s","number.sem_export_guard_release_s","number.sem_ev_morning_window_hours","number.sem_battery_morning_drain_floor_soc","number.sem_cheap_price_threshold","number.sem_expensive_price_threshold","number.sem_minimum_solar_power","number.sem_update_interval","number.sem_ev_enable_delay_seconds","number.sem_ev_disable_delay_seconds","number.sem_regulation_offset","switch.sem_observer_mode","switch.sem_simulation_tab","sensor.sem_diag_grid_sign","sensor.sem_diag_battery_sign"],ea=new Set(["text","input_text","number","input_number","select","input_select"]),sa=["switch","input_boolean",...ea],ia=new Set(["battery_soc_sensor","tariff_schedule_entity","grid_power_sensor","solar_production_sensor","battery_power_sensor","house_power_sensor","heat_pump_relay1_entity","heat_pump_relay2_entity","heat_pump_relay1_on_value","heat_pump_relay1_off_value","heat_pump_relay2_on_value","heat_pump_relay2_off_value","heat_pump_climate_entity","heat_pump_power_sensor","heat_pump_temperature_sensor","heat_pump_invert_sg_ready","heat_pump_tariff_rate","heat_pump_tariff_entity","heat_pump_tariff_meter","hot_water_entity","hot_water_power_sensor","hot_water_temperature_sensor","battery_force_discharge_control_entity","battery_strategy_control_entity","battery_discharge_control_entity","battery_charge_end_soc_entity","battery_discharge_protection_enabled","battery_setpoint_bidirectional","battery_setpoint_model","battery_power_direction_entity","battery_direction_discharge_value","battery_direction_charge_value"]);kt("sem-config-card",class extends Lt{static get watchedEntities(){return ta}static get properties(){return{...super.properties,_retentionBusy:{state:!0},_retentionMsg:{state:!0},_showHelp:{state:!0},_advanced:{state:!0},_lmAdvancedOpen:{state:!0},_entryId:{state:!0},_saveStatus:{state:!0},_signBusy:{state:!0},_signMsg:{state:!0},_battSignBusy:{state:!0},_battSignMsg:{state:!0},_pending:{state:!0},_applying:{state:!0},_pendingRemove:{state:!0},_chargerBusy:{state:!0},_staged:{state:!0},_secApplying:{state:!0},_helpOpen:{state:!0}}}constructor(){super(),this._collapsed={overview:!1,ev_chargers:!0,battery_zones:!0,tariff:!0,heat_pump:!0,hot_water:!0,battery_scheduler:!0,load_management:!0,forecast:!0,pv_strings:!0,notifications:!0,advanced:!0},this._showHelp=!1,this._advanced=Di(),this._onViewMode=t=>{const e=t&&t.detail&&"boolean"==typeof t.detail.all?t.detail.all:Di();e!==this._advanced&&(this._advanced=e)},this._rows=null,this._lmAdvancedOpen=!1,this._entryId="",this._saveStatus={},this._statusTimers=new Set,this._signBusy=!1,this._signMsg="",this._battSignBusy=!1,this._battSignMsg="",this._pending={},this._applying=!1,this._pendingRemove="",this._chargerBusy=!1,this._staged={},this._secApplying="",this._helpOpen={},this._secOf={},this._sec=null}disconnectedCallback(){super.disconnectedCallback(),window.removeEventListener(Mi,this._onViewMode);for(const t of this._statusTimers)clearTimeout(t);this._statusTimers.clear(),Object.values(this._saveStatus||{}).includes("ok")&&(this._saveStatus=Object.fromEntries(Object.entries(this._saveStatus).filter(([,t])=>"ok"!==t)))}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||"sensor.sem_",t.entry_id&&(this._entryId=t.entry_id)}async _ensureEntryId(){if(this._entryId||!this._hass)return this._entryId;try{const t=await this._hass.callWS({type:"config_entries/get",domain:"solar_energy_management"});Array.isArray(t)&&t.length>0&&(this._entryId=t[0].entry_id,this.requestUpdate())}catch(t){console.warn("[sem-config-card] entry lookup failed",t)}return this._entryId}async _saveOption(t,e,s){return this._saveOptions({[t]:e},s||t)}async _saveOptions(t,e,s=t){const i=await this._ensureEntryId();this._saveStatus={...this._saveStatus,[e]:"saving"};try{await this._hass.callService("solar_energy_management","set_option",{options:{...t},...i?{entry_id:i}:{}}),this._saveStatus={...this._saveStatus,[e]:"ok"},this._options={...this._options,...s},this.requestUpdate();const r=setTimeout(()=>{this._statusTimers.delete(r),this._saveStatus={...this._saveStatus},delete this._saveStatus[e],this.requestUpdate()},1200);this._statusTimers.add(r)}catch(s){console.error("[sem-config-card] save failed",Object.keys(t),s),this._saveStatus={...this._saveStatus,[e]:s?.message||"save failed"},this.requestUpdate()}}_options={};_revealed=new Set;async _refreshOptions(){if(this._hass)try{const t=await this._hass.callService("solar_energy_management","get_config",{},void 0,void 0,!0),e=t?.response?.config;if(!e||"object"!=typeof e)return;this._options=e,t?.response?.entry_id&&!this._entryId&&(this._entryId=t.response.entry_id),this.requestUpdate()}catch(t){console.warn("[sem-config-card] get_config failed",t)}}connectedCallback(){super.connectedCallback(),window.addEventListener(Mi,this._onViewMode),this._advanced=Di(),this._hass?this._ensureEntryId().then(()=>this._refreshOptions()):this._needsEntryLookup=!0}set hass(t){super.hass=t,this._needsEntryLookup&&t&&(this._needsEntryLookup=!1,this._ensureEntryId().then(()=>this._refreshOptions()))}get hass(){return super.hass}_toggleHelp(){this._showHelp=!this._showHelp}_setView(t){const e=!!t;this._advanced=e,Ei(e)}_isValueContact(t){const e=String(t||"");return ea.has(e.split(".")[0])}_showsControl(t){if(this._advanced)return!0;const e=String(t||"").replace(/^[a-z_]+\.sem_/,"");return Vr[e]?!!(this._options||{})[Vr[e]]:!!qr.has(e)&&(!Yr[e]||Yr[e]===this._tariffMode())}_showsChargerControl(t){return!!this._advanced||Zr.has(String(t||""))}_gate(t){return this._countRow(this._showsControl(t))}_gateCharger(t){return this._countRow(this._showsChargerControl(t))}_countRow(t){return this._rows&&(t?this._rows.shown+=1:this._rows.hidden+=1),t}_hideRows(t){return this._rows&&(this._rows.hidden+=t),K}_tariffMode(){const t=(this._options||{}).tariff_mode||"static";return String(this._stagedVal("opt:tariff_mode",t))}_pickTariffMode(t){this._stage("opt:tariff_mode","option",t);const e={...this._pending},s={...this._staged};"calendar"!==t&&delete e.tariff_schedule_entity,"dynamic"!==t&&delete s["opt:tariff_classification_mode"],this._showsControl("electricity_off_peak_rate")||delete s["opt:electricity_off_peak_rate"],this._pending=e,this._staged=s}_toggleSection(t){this._collapsed={...this._collapsed,[t]:!this._collapsed[t]},this.requestUpdate()}_val(t){const e=this._hass?.states[`${this._prefix}${t}`];return e&&"unavailable"!==e.state&&"unknown"!==e.state?e.state:""}_bin(t){return"on"===this._hass?.states[`binary_sensor.sem_${t}`]?.state}_valNum(t,e=null){return At(this._hass?.states[`${this._prefix}${t}`])??e}_switchOn(t){const e=this._hass?.states[`switch.sem_${t}`];return"on"===e?.state}async _toggleSwitch(t){const e=this._hass?.states[t];e&&await this._hass.callService("switch","on"===e.state?"turn_off":"turn_on",{entity_id:t})}async _stepNumber(t,e){const s=this._hass?.states[t];if(!s)return;const i=parseFloat(s.attributes.step)||1,r=Number.isFinite(parseFloat(s.attributes.min))?parseFloat(s.attributes.min):0,a=Number.isFinite(parseFloat(s.attributes.max))?parseFloat(s.attributes.max):100;let n=(parseFloat(s.state)||0)+e*i;n=Math.max(r,Math.min(a,n)),await this._hass.callService("number","set_value",{entity_id:t,value:n})}async _selectOption(t,e){await this._hass.callService("select","select_option",{entity_id:t,option:e})}async _setNumber(t,e){const s=this._hass?.states[t];if(!s)return;const i=parseFloat(s.attributes.min),r=parseFloat(s.attributes.max);let a=e;Number.isNaN(i)||(a=Math.max(i,a)),Number.isNaN(r)||(a=Math.min(r,a)),await this._hass.callService("number","set_value",{entity_id:t,value:a})}_num(t,e=null){const s=this._hass?.states[t];if(!s||"unavailable"===s.state||"unknown"===s.state)return e;const i=parseFloat(s.state);return Number.isNaN(i)?e:i}_overviewSubtitle(){const t=this._chargersList().length,e=this._bin("heat_pump_registered"),s=[];return s.push(`${t} ${this._t("config_subtitle_chargers")}`),e&&s.push(this._t("config_subtitle_heatpump_on")),s.join(" · ")}_evChargersSubtitle(){return`${this._chargersList().length}`}_batteryZonesSubtitle(){const t=It(this._valNum("battery_soc",null)).label;return`${this._t("soc")} ${t}`}_tariffSubtitle(){const t=this._valLabel("tariff_provider")||"—",e=this._val("tariff_price_level")||"";return e?`${t} · ${this._t(ke(e))||e}`:t}_heatPumpSubtitle(){return this._bin("heat_pump_registered")?this._t("configured"):this._t("not_configured")}_hotWaterSubtitle(){return(this._options||{}).hot_water_entity?this._t("configured"):this._t("not_configured")}_loadMgmtSubtitle(){return this._valLabel("load_management_status")}_forecastSubtitle(){const t=this._forecastProviderLabel(this._val("forecast_source"));return t||this._t("not_configured")}_chargersList(){const t=new Set;for(const e of Object.keys(this._hass?.states||{})){const s=e.match(/^number\.sem_charger_(.+)_minimum_current$/);s&&t.add(s[1])}return Array.from(t).sort()}_openHaSettings(t=""){window.history.pushState(null,"","/config/integrations/integration/solar_energy_management"),window.dispatchEvent(new PopStateEvent("popstate"))}_renderStepper(t,e,s,i){return this._renderZoneKnob(t,e,s,i)}_renderToggle(t,e,s,i){const r=this._hass?.states[t];if(!r)return K;if(!this._gate(t))return K;this._reg(t);const a=this._isDirty(t),n="on"===String(this._stagedVal(t,r.state));return H`
            <div class="stepper-cell ${a?"dirty":""}">
                <div class="toggle-row">
                    <span class="toggle-label">${this._t(e)}${a?H`<span class="dirty-dot">●</span>`:K}${this._helpBtn(i)}</span>
                    <div class="toggle-track ${n?"on":""}"
                         @click=${()=>this._stage(t,"switch",n?"off":"on")}>
                        <div class="toggle-thumb"></div>
                    </div>
                </div>
                ${this._helpBlock(i)}
            </div>
        `}_renderSelect(t,e,s,i){const r=this._hass?.states[t];if(!r)return K;if(!this._gate(t))return K;this._reg(t);const a=this._isDirty(t),n=String(this._stagedVal(t,r.state)),o=r.attributes.options||[];return H`
            <div class="stepper-cell ${a?"dirty":""}">
                <div class="ctrl-row">
                    <span class="ctrl-label">${this._t(e)}${a?H`<span class="dirty-dot">●</span>`:K}${this._helpBtn(i)}</span>
                    <select class="sem-select" .value=${n}
                            @change=${e=>this._stage(t,"select",e.target.value)}>
                        ${o.map(t=>H`<option value="${t}" ?selected=${t===n}>${this._t(t.toLowerCase())||t}</option>`)}
                    </select>
                </div>
                ${this._helpBlock(i)}
            </div>
        `}_renderHaSettingsButton(t){return H`
            <button class="ha-settings-btn" @click=${()=>this._openHaSettings()}>
                <ha-icon icon="mdi:cog-outline" style="--mdc-icon-size:14px"></ha-icon>
                ${this._t(t)}
            </button>
        `}_setupItems(){const t=this._options||{};return[{key:"energy",labelKey:"config_overview_energy_dashboard",icon:"mdi:flash",color:"#ff9800",sectionId:"overview",done:!!this._hass?.states["sensor.sem_charging_state"]},{key:"ev",labelKey:"config_overview_chargers",icon:"mdi:ev-station",color:"#5BC8D8",sectionId:"ev_chargers",done:this._chargersList().length>0},{key:"hp",labelKey:"heat_pump_title",icon:"mdi:heat-pump",color:"#4db6ac",sectionId:"heat_pump",done:this._bin("heat_pump_registered")},{key:"hw",labelKey:"config_section_hot_water",icon:"mdi:water-boiler",color:"#5BC8D8",sectionId:"hot_water",done:!!t.hot_water_entity},{key:"tariff",labelKey:"config_section_tariff",icon:"mdi:cash-multiple",color:"#8353d1",sectionId:"tariff",done:"dynamic"===t.tariff_mode?!!t.dynamic_tariff_entity:"calendar"===t.tariff_mode?!!t.tariff_schedule_entity:!!t.electricity_import_rate},{key:"battery",labelKey:"config_section_battery_zones",icon:"mdi:battery-charging",color:"#4db6ac",sectionId:"battery_zones",done:this._hasBattery()},{key:"loads",labelKey:"config_section_load_management",icon:"mdi:flash-alert",color:"#ff9800",sectionId:"load_management",optional:!0,done:!!t.load_management_enabled}]}_sectionConfigured(t){const e=this._setupItems().find(e=>e.sectionId===t);if(e)return!!e.done;const s=this._options||{};return"battery_scheduler"===t?!!s.battery_charge_scheduler_enabled:"notifications"===t&&!!s.enable_mobile_notifications}_openSection(t){this._revealed=new Set([...this._revealed,t]),this._collapsed={...this._collapsed,[t]:!1},this.requestUpdate()}_renderOverview(t){const e=this._setupItems(),s=e.filter(t=>!t.optional),i=s.filter(t=>t.done).length,r=s.length,a=i===r,n=r?Math.round(i/r*100):100;return H`
            <div class="setup-progress">
                <div class="setup-progress-top">
                    <span class="setup-progress-label">
                        ${a?this._t("config_setup_done"):this._t("config_setup_progress").replace(/\{done\}/g,String(i)).replace(/\{total\}/g,String(r))}
                    </span>
                    <span class="setup-progress-pct">${n}%</span>
                </div>
                <div class="setup-progress-bar">
                    <div class="setup-progress-fill ${a?"done":""}" style=${`width:${n}%`}></div>
                </div>
            </div>
            <div class="chips">
                ${e.map(t=>H`
                    <div class="chip ${t.done?"":"chip-todo"}"
                        @click=${t.done?void 0:()=>this._openSection(t.sectionId)}>
                        <ha-icon icon="${t.icon}" style="--mdc-icon-size:16px;color:${t.color}"></ha-icon>
                        <div class="chip-label">${this._t(t.labelKey)}</div>
                        <div class="chip-value ${t.done?"c-ok":t.optional?"":"c-warn"}">
                            ${t.done?"✓":t.optional?this._t("config_setup_optional"):this._t("config_setup_action")}
                        </div>
                    </div>`)}
            </div>
            <div class="overview-help">${this._t("config_overview_help")}</div>
            <div class="overview-actions">
                ${this._renderHaSettingsButton("config_open_ha_settings")}
            </div>
        `}_renderEvChargers(t){const e=this._options||{},s=e.ev_chargers||[],i=this._chargersList();if(0===s.length&&0===i.length)return H`
                <div class="empty-state">
                    <ha-icon icon="mdi:ev-station-outline" style="--mdc-icon-size:32px;color:#5BC8D8;opacity:0.7"></ha-icon>
                    <div class="empty-title">${this._t("config_ev_no_chargers")}</div>
                    <button class="add-charger-btn" ?disabled=${this._chargerBusy} @click=${()=>this._addCharger()}>
                        <ha-icon icon="mdi:plus" style="--mdc-icon-size:16px"></ha-icon>
                        ${this._t("config_ev_add_charger")}
                    </button>
                </div>
            `;const r=s.length?s:i.map(t=>({}));return H`
            ${r.map((s,r)=>{const a=s.id||i[r];return a?H`
                <div class="charger-block">
                    <div class="charger-block-title">
                        <ha-icon icon="mdi:ev-station" style="--mdc-icon-size:18px;color:#5BC8D8"></ha-icon>
                        <span style="flex:1">${this._chargerFriendlyName(a)}</span>
                        ${this._pendingRemove===a?K:H`
                            <button class="charger-remove-x" title="${this._t("config_ev_remove")}"
                                ?disabled=${this._chargerBusy}
                                @click=${()=>{this._chargerBusy||(this._pendingRemove=a,this.requestUpdate())}}>✕</button>`}
                    </div>
                    ${this._renderRoleLegend(a)}
                    ${this._pendingRemove===a?H`
                        <div class="charger-remove-confirm">
                            <span>${this._t("config_ev_remove_confirm")}</span>
                            <button class="charger-remove-cancel" @click=${()=>{this._pendingRemove="",this.requestUpdate()}}>${this._t("config_discard")}</button>
                            <button class="charger-remove-go" @click=${()=>this._removeCharger(a)}>${this._t("config_ev_remove")}</button>
                        </div>`:K}
                    ${""}
                    ${this._renderPickerNested(r,a,"ev_connected_sensor","config_ev_connected_sensor",["binary_sensor","sensor"],null,e,"config_help_ev_connected_sensor")}
                    ${this._renderPickerNested(r,a,"ev_charging_power_sensor","config_ev_charging_power","sensor","power",e,"config_help_ev_charging_power")}
                    ${this._renderPickerNested(r,a,"ev_current_control_entity","config_ev_current_control","number",null,e,"config_help_ev_current_control")}
                    ${""}
                    ${this._renderPickerNested(r,a,"ev_start_stop_entity","config_ev_start_stop",["switch","button"],null,e,"config_help_ev_start_stop")}
                    ${""}
                    ${this._renderToggleNested(r,a,"ev_phase_switching_enabled","config_ev_phase_switching",e,"config_help_ev_phase_switching")}
                    ${this._renderPickerNested(r,a,"ev_phase_switch_entity","config_ev_phase_switch",["select","number","switch","input_select","input_number","input_boolean"],null,e,"config_help_ev_phase_switch")}
                    ${s.ev_phase_switch_entity?H`
                        ${this._renderTextNested(r,a,"ev_phase_switch_value_1p","config_ev_phase_1p",e,"config_help_ev_phase_values","1 / off / einphasig")}
                        ${this._renderTextNested(r,a,"ev_phase_switch_value_3p","config_ev_phase_3p",e,"config_help_ev_phase_values","3 / on / dreiphasig")}`:K}
                    ${""}
                    ${this._renderPickerNested(r,a,"ev_charge_mode_entity","config_ev_charge_mode",["select","input_select"],null,e,"config_help_ev_charge_mode")}
                    ${s.ev_charge_mode_entity?H`
                        ${this._renderTextNested(r,a,"ev_charge_mode_start","config_ev_charge_mode_start",e,"config_help_ev_charge_mode","On / 2")}
                        ${this._renderTextNested(r,a,"ev_charge_mode_stop","config_ev_charge_mode_stop",e,"config_help_ev_charge_mode","Off / 1")}`:K}
                    ${this._renderPickerNested(r,a,"vehicle_soc_entity","config_ev_vehicle_soc","sensor",null,e,"config_help_ev_vehicle_soc")}
                    ${this._renderTargetTypeSelectNested(r,a,s,e)}
                    ${this._renderExtModeNested(r,a,s,e)}
                    ${s.external_control_mode&&"none"!==s.external_control_mode?this._renderPickerNested(r,a,"external_control_indicator","config_ext_ctrl_entity",["binary_sensor","switch","input_boolean","select","input_select"],null,e,"config_help_ext_ctrl"):K}
                    ${""}
                    <div class="stepper-pair">
                        ${this._renderStepper(`number.sem_charger_${a}_minimum_current`,"min_amps",t,"tile_help_min_amps")}
                        ${this._renderStepper(`number.sem_charger_${a}_maximum_current`,"max_amps",t,"tile_help_max_amps")}
                    </div>
                    ${""}
                    ${""}
                    ${"soc"===s.ev_target_type?H`
                        <div class="stepper-pair">
                            ${this._renderStepper(`number.sem_charger_${a}_target_soc`,"config_ev_target_soc",t,"config_help_ev_target_soc")}
                            ${this._renderStepper(`number.sem_charger_${a}_target_soc_max`,"config_ev_target_soc_max",t,"config_help_ev_target_soc_max")}
                        </div>`:H`
                        <div class="stepper-pair">
                            ${this._renderStepper(`number.sem_charger_${a}_daily_ev_target`,"config_ev_daily_target",t,"config_help_ev_daily_target")}
                            ${this._renderStepper(`number.sem_charger_${a}_daily_ev_target_max`,"config_ev_daily_target_max",t,"config_help_ev_daily_target_max")}
                        </div>`}
                    ${""}
                    ${this._renderToggleNested(r,a,"finish_by_departure","config_finish_by_departure",e,"config_help_finish_by_departure")}
                    ${""}
                    <div class="stepper-pair">
                        ${this._renderStepper(`number.sem_charger_${a}_ev_battery_capacity_kwh`,"capacity_kwh",t,"tile_help_capacity")}
                        ${this._renderStepper(`number.sem_charger_${a}_ev_kwh_per_100km`,"config_ev_kwh_per_100km",t,"config_help_ev_kwh_per_100km")}
                    </div>
                    <div class="stepper-pair">
                        ${this._renderStepper(`number.sem_charger_${a}_ev_phases`,"config_ev_phases",t,"config_help_ev_phases")}
                    </div>
                </div>
            `:K})}
            <div class="section-footer">
                <button class="add-charger-btn" ?disabled=${this._chargerBusy} @click=${()=>this._addCharger()}>
                    <ha-icon icon="mdi:plus" style="--mdc-icon-size:16px"></ha-icon>
                    ${this._t("config_ev_add_charger")}
                </button>
            </div>
        `}_chargerFriendlyName(t){return(this._hass?.states[`number.sem_charger_${t}_minimum_current`]?.attributes?.friendly_name||t).replace(/\s+Min Amps$/i,"")}_renderZoneKnob(t,e,s,i){const r=this._hass?.states[t];if(!r)return K;if(!this._gate(t))return K;this._reg(t);const a=parseFloat(r.state)||0,n=this._isDirty(t),o=Number(this._stagedVal(t,a)),l=parseFloat(r.attributes.min),c=parseFloat(r.attributes.max),d=Number.isNaN(l)?0:l,p=Number.isNaN(c)?100:c,_=parseFloat(r.attributes.step)||1,h=r.attributes.unit_of_measurement||"",u=_<1?1:0,g=p>d?Math.round((o-d)/(p-d)*100):0,m=e=>{const s=Math.max(d,Math.min(p,o+e*_));this._stage(t,"number",s)};return H`
            <div class="zone-knob ${n?"dirty":""}">
                <div class="zone-knob-top">
                    <span class="zone-knob-label">${this._t(e)}${this._helpBtn(i)}</span>
                    <span class="zone-chip">${n?H`<span class="dirty-dot">●</span>`:K}${o.toFixed(u)}${h?" "+h:""}</span>
                </div>
                <div class="zone-knob-slider">
                    <button class="zone-mini" @click=${()=>m(-1)}>−</button>
                    <input type="range" class="zone-range"
                        min=${d} max=${p} step=${_} .value=${String(o)}
                        style=${`--fill:${g}%`}
                        @change=${e=>this._stage(t,"number",parseFloat(e.target.value))} />
                    <button class="zone-mini" @click=${()=>m(1)}>+</button>
                </div>
                ${this._helpBlock(i,r.attributes.sem_default,h,t,"number")}
            </div>
        `}_renderSocZoneStrip(t){const e=this._num("number.sem_battery_priority_soc"),s=this._num("number.sem_battery_buffer_soc"),i=this._num("number.sem_battery_auto_start_soc");if(null==e||null==s||null==i)return K;const r=this._num("sensor.sem_battery_soc"),a=t=>Math.max(0,Math.min(100,t));return H`
            <div class="soc-strip">
                <div class="soc-bar">
                    <div class="soc-zone" style=${`width:${a(e)}%;background:#e57373`}></div>
                    <div class="soc-zone" style=${`width:${a(s-e)}%;background:#ffb74d`}></div>
                    <div class="soc-zone" style=${`width:${a(i-s)}%;background:#81c784`}></div>
                    <div class="soc-zone" style=${`width:${a(100-i)}%;background:#64b5f6`}></div>
                    ${null!=r?H`<div class="soc-now" style=${`left:${a(r)}%`} title="SOC ${r}%"></div>`:K}
                    <div class="soc-tick" style=${`left:${a(e)}%`}><span>${e}</span></div>
                    <div class="soc-tick" style=${`left:${a(s)}%`}><span>${s}</span></div>
                    <div class="soc-tick" style=${`left:${a(i)}%`}><span>${i}</span></div>
                </div>
                <div class="soc-legend">
                    <span><i style="background:#e57373"></i>${this._t("zone_legend_reserve")}</span>
                    <span><i style="background:#ffb74d"></i>${this._t("zone_legend_buffer")}</span>
                    <span><i style="background:#81c784"></i>${this._t("zone_legend_assist")}</span>
                    <span><i style="background:#64b5f6"></i>${this._t("zone_legend_surplus")}</span>
                </div>
            </div>
        `}_detectionReport(){const t=this._hass?.states?.["sensor.sem_diag_charger_control"];return t?.attributes?.detection_report||null}_detectedHardwareSubtitle(){const t=this._detectionReport();if(!t)return this._t("config_detect_none");const e=(t.chargers||[]).length,s=(t.near_misses||[]).length,i=((t.census||{}).unknown_energy_domains||[]).length+((t.census||{}).rows_matched_nothing||[]).length;let r=`${e} ${this._t("config_detect_chargers")}`;return s&&(r+=` · ${s} ${this._t("config_detect_near_misses")}`),i&&(r+=` · ${i} ${this._t("config_census_gaps")}`),r}_renderDetectedHardware(t){const e=this._detectionReport();if(!e)return H`<div class="setting-help-text">${this._t("config_detect_none")}</div>`;const s=e.chargers||[],i=e.near_misses||[],r=e.roster_proposals||[],a=(t,e)=>Object.entries(e).reduce((t,[e,s])=>t.split("{"+e+"}").join(s),this._t(t)),n=t=>{switch(t.action){case"observe_only":return this._t("config_proposed_observe_only");case"not_loaded":return this._t("config_proposed_not_loaded");case"no_unit":return a("config_proposed_no_unit",{wanted:t.unit_wanted||""});case"unit_mismatch":return a("config_proposed_unit_mismatch",{seen:t.unit_seen||"?",wanted:t.unit_wanted||""});case"options_unmapped":return a("config_proposed_options_unmapped",{missing:(t.values_missing||[]).join(", "),options:(t.options||[]).join(", ")});case"pair_incomplete":return a("config_proposed_pair_incomplete",{missing:(t.missing_role||[]).join(", ")});case"pair_blocked":return a("config_proposed_pair_blocked",{missing:(t.missing_role||[]).join(", ")});case"per_charger":return this._t("config_proposed_per_charger");default:return t.reason||""}},o=(t,e)=>{const s=this._saveStatus?.[e];return H`
                <button class="sem-btn" ?disabled=${"saving"===s}
                    @click=${()=>this._saveOptions(t,e)}>
                    ${"saving"===s?this._t("config_proposed_using"):this._t("config_proposed_use")}
                </button>
                ${"ok"===s?H`<span style="opacity:.7"> ✓</span>`:K}
                ${s&&"ok"!==s&&"saving"!==s?H`<span style="opacity:.7"> ${s}</span>`:K}`},l=(t,e)=>{const s=e.entity||e.service||(e.candidates||[]).join(" / ")||"",i=Pr(e,e.entity,this._options),r=Ur(i,this._options),a=n(e),l=(e.alternatives||[]).filter(t=>t&&t.entity);return H`
            <div class="row">
                <span class="lbl">${t}</span>
                <span style="font-family:monospace;font-size:0.85em">${s}
                    <span style="opacity:.6"> · ${e.matched_key}</span>
                </span>
            </div>
            <div class="row" style="margin:-6px 0 6px">
                <span class="lbl"></span>
                <span>
                    ${"set_option"===e.action&&i&&!r?o(i,"prop_"+t):K}
                    ${r?H`<span style="opacity:.7">${this._t("config_proposed_already")}</span>`:K}
                    ${a?H`<span style="opacity:.7">${a}</span>`:K}
                </span>
            </div>
            ${l.map((s,i)=>{const r=!s.action||"set_option"===s.action,a=r?Pr(e,s.entity,this._options):null,l=r?"":n(s);return H`
                <div class="row" style="margin:-6px 0 6px">
                    <span class="lbl" style="opacity:.6">${this._t("config_proposed_or")}</span>
                    <span style="font-family:monospace;font-size:0.85em">${s.entity}
                        <span style="opacity:.6"> · ${s.matched_key}</span>
                        ${"set_option"===e.action&&a&&!Ur(a,this._options)?H` ${o(a,"prop_"+t+"_alt"+i)}`:K}
                        ${"set_option"===e.action&&l?H` <span style="opacity:.7;font-family:inherit">${l}</span>`:K}
                    </span>
                </div>`})}`},c=e.prober_candidates||[],d=e.disagreements||[],p=e.census||{},_=p.unknown_energy_domains||[],h=p.rows_matched_nothing||[],u=p.unknown_energy_domains_named||[];return H`
            <div class="setting-help-text" style="margin:0 0 6px">${this._t("config_detect_intro")}</div>
            ${_.length?H`
                <div class="row" style="color:var(--warning-color,#ffa726)">
                    <span class="lbl">${this._t("config_census_unknown")}</span>
                    <span style="font-family:monospace">${_.map(t=>{const e=u.find(e=>e&&e.domain===t);if(!e||!e.name)return t;const s=e.installs?` · ${e.installs} ${this._t("config_census_installs")}`:"";return`${e.name}${s}`}).join(", ")}</span>
                </div>`:K}
            ${h.length?H`
                <div class="row" style="color:var(--warning-color,#ffa726)">
                    <span class="lbl">${this._t("config_census_nomatch")}</span>
                    <span style="font-family:monospace">${h.join(", ")}</span>
                </div>`:K}
            ${s.map(t=>H`
                <div class="row" style="font-weight:600">
                    <span class="lbl">${this._t("config_detect_charger")}: ${t.platform}${t.name?" · "+t.name:""}</span>
                    <span>${t.control}${t.configured?H` · <span style="opacity:.7">✓ ${this._t("config_detect_configured")}</span>`:K}</span>
                </div>
                ${Object.entries(t.mapped||{}).map(([t,e])=>((t,e)=>H`
            <div class="row"><span class="lbl">${t}</span>
                <span style="font-family:monospace;font-size:0.85em">${e.entity||e.value||"—"}
                    ${e.device_class?H`<span style="opacity:.6"> · ${e.domain}/${e.device_class}</span>`:K}
                </span></div>`)(t,e))}
                ${(t.unmapped||[]).length?H`
                    <div class="setting-help-text" style="margin:2px 0 8px">
                        ${this._t("config_detect_unmapped")}: ${(t.unmapped||[]).map(t=>t.entity).join(", ")}
                    </div>`:K}
            `)}
            ${i.map(e=>{return H`
                <div class="row" style="color:${t.warn||"#ffb74d"}">
                    <span class="lbl">⚠ ${e.roster?.name||e.platform}</span>
                    <span>${a((s=e,{add:"config_detect_offer",watch:"config_detect_watch_only",report:"config_detect_near_miss"}[Lr(s)]),{roles:(e.charger_roles||[]).join(", ")})}</span>
                </div>
                <div class="setting-help-text" style="margin:-2px 0 8px">
                    ${(e.entities||[]).map(t=>t.entity).join(", ")}
                </div>
                ${e.suggested_charger?.id?H`
                    <div class="row" style="margin:-2px 0 8px">
                        <span class="lbl"></span>
                        <span>
                            <button class="sem-btn" ?disabled=${this._chargerBusy}
                                @click=${()=>this._addSuggestedCharger(e.suggested_charger)}>
                                ${this._t("config_near_miss_add")}
                            </button>
                        </span>
                    </div>`:"watch"===Lr(e)?H`
                    <div class="setting-help-text" style="margin:-2px 0 8px">
                        ${this._t(function(t){return(t&&t.choose_vehicle||[]).length?"config_detect_choose_vehicle_help":"config_detect_watch_only_help"}(e))}
                    </div>`:H`
                    <div class="row" style="margin:-2px 0 8px">
                        <span class="lbl"></span>
                        <span><a class="sem-btn" target="_blank" rel="noopener"
                                 href=${this._reportNearMissUrl(e)}>
                            ${this._t("config_near_miss_report")}
                        </a></span>
                    </div>`}
                ${Object.keys(e.proposed_roles||{}).length?H`
                    <div class="row" style="font-weight:600">
                        <span class="lbl">${this._t("config_proposed_roles")}</span>
                        <span style="opacity:.7">${this._t("config_proposed_unconfirmed")}</span>
                    </div>
                    ${Object.entries(e.proposed_roles).map(([t,e])=>l(t,e))}
                    <div class="setting-help-text" style="margin:2px 0 8px">
                        ${this._t("config_proposed_help")}
                    </div>`:K}`;var s})}
            ${r.map(t=>H`
                <div class="row" style="font-weight:600">
                    <span class="lbl">🧩 ${t.roster?.name||t.domain}</span>
                    <span style="opacity:.7">${this._t("config_proposed_unconfirmed")}</span>
                </div>
                ${Object.entries(t.proposed_roles||{}).map(([t,e])=>l(t,e))}
            `)}
            ${r.length?H`
                <div class="setting-help-text" style="margin:2px 0 8px">
                    ${this._t("config_proposed_help")}
                </div>`:K}
            ${d.filter(t=>"prober_only"===t.kind).map(t=>H`
                <div class="row"><span class="lbl">🔎 ${t.platform}</span>
                    <span>${this._t("config_detect_prober_only")}</span></div>`)}
            ${s.length||i.length||c.length?K:H`
                <div class="setting-help-text">${this._t("config_detect_nothing")}</div>`}
        `}_renderSourceCheck(t){const e=function(t){const e=[],s=jr(t("solar_power"));e.push({key:"solar",w:null===s?null:Math.max(0,s),dir:""});const i=Gr(jr(t("grid_import_power")),jr(t("grid_export_power")));e.push({key:"grid",w:null===i?null:Math.abs(i),dir:null===i||Math.abs(i)<50?"":i>0?"buying":"sending"});const r=Gr(jr(t("battery_charge_power")),jr(t("battery_discharge_power")));null!==r&&e.push({key:"battery",w:Math.abs(r),dir:Math.abs(r)<50?"":r>0?"charging":"giving"});const a=jr(t("home_consumption_power"));return e.push({key:"home",w:a,dir:""}),e}(t=>this._hass?.states[this._prefix+t]);this._countRow(!0);const s=e.some(t=>"battery"===t.key);return H`
            <div class="grid-sign-block source-check">
                <div class="setting-help-text" style="margin:0 0 4px">
                    ${this._t("config_check_intro")}</div>
                ${e.map(t=>H`
                    <div class="readonly-row">
                        <span class="ctrl-label">${this._t("config_check_"+t.key)}</span>
                        <span class="readonly-value">${t.dir?this._t("config_check_"+t.dir)+" ":""}${function(t){return null==t?"—":String(Math.round(t)).replace(/\B(?=(\d{3})+(?!\d))/g," ")+" W"}(t.w)}</span>
                    </div>`)}
                <div class="setting-help-text" style="margin:4px 0 0">
                    ${this._t("config_check_question")}</div>
                <div class="action-row">
                    <button class="action-btn" ?disabled=${this._signBusy}
                            @click=${()=>this._flipGridSign()}>
                        <ha-icon icon="mdi:swap-vertical-bold" style="--mdc-icon-size:16px"></ha-icon>
                        ${this._t("config_check_grid_wrong")}
                    </button>
                    ${s?H`
                    <button class="action-btn" ?disabled=${this._battSignBusy}
                            @click=${()=>this._flipBatterySign()}>
                        <ha-icon icon="mdi:swap-vertical-bold" style="--mdc-icon-size:16px"></ha-icon>
                        ${this._t("config_check_battery_wrong")}
                    </button>`:K}
                </div>
                ${this._signMsg?H`<div class="sign-feedback">${this._signMsg}</div>`:K}
                ${this._battSignMsg?H`<div class="sign-feedback">${this._battSignMsg}</div>`:K}
                <div class="setting-help-text" style="margin:2px 0 6px">
                    ${this._t("config_check_wrong_sensor")}</div>
            </div>
        `}_renderSensorSources(t){const e=this._options||{};return H`
            ${this._renderSourceCheck(t)}
            <div class="setting-help-text" style="margin:0 0 6px">
                ${this._t("config_sources_intro")}</div>
            ${this._renderPicker("grid_power_sensor","config_grid_power_sensor","sensor","power",e,"config_help_grid_power_sensor")}
            ${this._sourceUnavailableWarning("grid_power_sensor",e,t)}
            ${this._renderPicker("solar_production_sensor","config_solar_production_sensor","sensor","power",e,"config_help_solar_production_sensor")}
            ${this._sourceUnavailableWarning("solar_production_sensor",e,t)}
            ${this._renderPicker("battery_power_sensor","config_battery_power_sensor","sensor","power",e,"config_help_battery_power_sensor")}
            ${this._sourceUnavailableWarning("battery_power_sensor",e,t)}
            ${""}
            ${this._renderPicker("house_power_sensor","config_house_power_sensor","sensor","power",e,"config_help_house_power_sensor")}
            ${this._sourceUnavailableWarning("house_power_sensor",e,t)}
        `}_sensorSourcesSubtitle(){const t=this._options||{},e=["grid_power_sensor","solar_production_sensor","battery_power_sensor","house_power_sensor"].filter(e=>t[e]).length;return e?`${e} ${this._t("config_sources_overridden")}`:this._t("config_sources_all_auto")}_sourceUnavailableWarning(t,e,s){const i=e[t];if(!i||!this._hass)return K;const r=this._hass.states[i];return r&&"unavailable"!==r.state&&"unknown"!==r.state?K:H`<div class="setting-help-text"
            style="color:${s.warn||"#ffb74d"};margin:-2px 0 6px">
            ⚠ ${i} — ${this._t("config_source_unavailable")}</div>`}_renderBatteryZones(t){const e=this._options||{};return H`
            ${this._renderSocZoneStrip(t)}
            ${""}
            ${this._renderPicker("battery_soc_sensor","config_battery_soc_sensor","sensor",null,e,"config_help_battery_soc_sensor")}
            ${""}
            ${this._renderPicker("battery_cycles_sensor","config_battery_cycles_sensor","sensor",null,e,"config_help_battery_cycles_sensor")}
            ${this._renderZoneKnob("number.sem_battery_priority_soc","priority_soc",t,"zone_help_priority")}
            ${this._renderZoneKnob("number.sem_battery_buffer_soc","buffer_soc",t,"zone_help_buffer")}
            ${this._renderZoneKnob("number.sem_battery_auto_start_soc","auto_start_soc",t,"zone_help_autostart")}
            ${this._renderZoneKnob("number.sem_battery_assist_min_surplus","assist_min_surplus",t,"zone_help_assist_min_surplus")}
            ${this._renderZoneKnob("number.sem_battery_assist_max_power","assist_max_power",t,"zone_help_assist_max_power")}
            ${""}
            <div style="margin-top:6px;border-top:1px solid ${t.surfaceBorder};padding-top:4px"></div>
            ${this._renderOptionToggle("battery_discharge_protection_enabled","config_batt_protection",e,"config_help_batt_protection",!0)}
            ${this._renderZoneKnob("number.sem_battery_max_discharge_power","battery_max_discharge_power",t,"config_help_batt_max_discharge")}
            ${this._renderPicker("battery_discharge_control_entity","config_batt_discharge_entity","number",null,e,"config_help_batt_discharge_entity")}
            ${""}
            ${(()=>{const t=this._batteryCount();return t<2||!this._showsControl("battery_discharge_control_entity")?K:H`${Array.from({length:t},(s,i)=>this._renderBatteryListPicker("battery_discharge_control_entities","config_batt_discharge_entity",["number"],i,t,e,"config_help_batt_discharge_entity_each"))}`})()}
            ${this._renderExtModeOption(e)}
            ${e.battery_external_control_mode&&"none"!==e.battery_external_control_mode?this._renderPicker("battery_external_control_indicator","config_ext_ctrl_entity",["binary_sensor","switch","input_boolean","select","input_select"],null,e,"config_help_ext_ctrl"):K}
            ${""}
            ${this._renderPicker("battery_charge_end_soc_entity","config_batt_charge_end_entity",["number","sensor","input_number"],null,e,"config_help_batt_charge_end_entity")}
            ${(()=>{const t=this._batteryCount();return t<2||!this._showsControl("battery_charge_end_soc_entity")?K:H`${Array.from({length:t},(s,i)=>this._renderBatteryListPicker("battery_charge_end_soc_entities","config_batt_charge_end_entity",["number","sensor","input_number"],i,t,e,"config_help_batt_charge_end_entity_each"))}`})()}
        `}_renderTextOption(t,e,s,i,r){if(!this._gate(t))return K;const a=s[t]??"",n=this._saveStatus[t];return H`
            <div class="row">
                <span class="lbl" title="${i?this._t(i):""}">${this._t(e)}</span>
                <input type="text" class="txt-opt" .value=${String(a)}
                       placeholder="${r||""}"
                       @keydown=${t=>{"Enter"===t.key&&t.target.blur()}}
                       @blur=${e=>{const s=e.target.value.trim();s!==String(a)&&this._saveOption(t,s,t)}} />
                ${"saving"===n?H`<span class="sv">…</span>`:"ok"===n?H`<span class="sv ok">✓</span>`:"err"===n?H`<span class="sv err">!</span>`:K}
            </div>
        `}_renderValueLayer(t,e){const s=["none","nl_2027","custom"].map(t=>({value:t,label:this._t("config_value_preset_"+t)})),i=["all_in","spot_incl_vat","spot"].map(t=>({value:t,label:this._t("config_price_basis_"+t)})),r=["none","per_kwh","tiered","fixed_monthly"].map(t=>({value:t,label:this._t("config_fee_model_"+t)})),a=this._stagedVal("opt:feed_in_fee_model",t.feed_in_fee_model??"none"),n="fixed_monthly"===a?`${e}/Mt`:`${e}/kWh`,o=`${e}/kWh`,l="all_in"===this._stagedVal("opt:import_price_basis",t.import_price_basis??"all_in"),c=e+"/kWh";return H`
            ${this._renderOptionSelect("tariff_value_preset","config_value_preset",s,t,"config_help_value_preset","none")}
            ${this._renderOptionSelect("import_price_basis","config_price_basis",i,t,"config_help_price_basis","all_in")}
            ${l?H`<div class="setting-help-text">${this._t("config_value_needs_spot_basis")}</div>`:K}
            ${this._renderOptionNumberInput("import_markup","config_import_markup",{min:0,max:1e4,step:1e-4,unit:c,default:0,disabled:l},t,"config_help_import_markup")}
            ${this._renderOptionNumberInput("import_energy_tax","config_import_energy_tax",{min:0,max:1e4,step:1e-4,unit:c,default:0,disabled:l},t,"config_help_import_energy_tax")}
            ${this._renderOptionNumberInput("import_vat_percent","config_import_vat_percent",{min:0,max:100,step:.1,unit:"%",default:0,disabled:l},t,"config_help_import_vat_percent")}
            ${this._renderOptionSelect("feed_in_fee_model","config_fee_model",r,t,"config_help_fee_model","none")}
            ${"per_kwh"===a||"fixed_monthly"===a?this._renderOptionNumberInput("feed_in_fee","config_feed_in_fee",{min:0,max:1e5,step:1e-4,unit:n,default:0},t,"config_help_feed_in_fee"):K}
            ${"tiered"===a?this._renderOptionTextInput("feed_in_fee_tiers","config_feed_in_fee_tiers",t,"config_help_feed_in_fee_tiers","0:0, 1000:0.02, 3000:0.05"):K}
            ${this._renderOptionNumberInput("export_value_threshold","config_export_value_threshold",{min:-1e4,max:1e4,step:1e-4,unit:o,default:0},t,"config_help_export_value_threshold")}
        `}_renderTariff(t){const e=this._options||{},s=this._hass?.states["sensor.sem_tariff_current_import_rate"],i=s?s.state:"—",r=s?.attributes?.unit_of_measurement||"",a=this._hass?.config?.currency||"EUR",n=[{value:"static",label:this._t("config_tariff_mode_static")},{value:"dynamic",label:this._t("config_tariff_mode_dynamic")},{value:"calendar",label:this._t("config_tariff_mode_calendar")}],o=[{value:"percentile",label:this._t("config_tariff_class_percentile")},{value:"static",label:this._t("config_tariff_class_static")}],l=this._tariffMode();return H`
            <div class="readonly-row tariff-rate-row">
                <ha-icon icon="mdi:flash" style="--mdc-icon-size:18px;color:#ff9800"></ha-icon>
                <span class="ctrl-label" style="flex:1">${this._t("current_electricity_price")}</span>
                <span class="readonly-value tariff-rate-value">${i} ${r}</span>
            </div>
            ${this._renderOptionSelect("tariff_mode","config_tariff_mode",n,e,"config_help_tariff_mode","static",t=>this._pickTariffMode(t))}
            ${"dynamic"===l?H`
                ${this._renderPicker("dynamic_tariff_entity","config_dynamic_tariff_entity","sensor",null,e,"config_help_dynamic_tariff_entity")}
                ${this._renderPicker("dynamic_forecast_entity","config_dynamic_forecast_entity","sensor",null,e,"config_help_dynamic_forecast_entity")}
                ${this._renderPicker("dynamic_feedin_entity","config_dynamic_feedin_entity","sensor",null,e,"config_help_dynamic_feedin_entity")}
                ${this._renderOptionSelect("tariff_classification_mode","config_tariff_class_mode",o,e,"config_help_tariff_class_mode","percentile")}
            `:K}
            ${""}
            ${this._renderPicker("grid_co2_entity","config_grid_co2_entity","sensor","co2_intensity",e,"config_help_grid_co2_entity")}
            ${""}
            ${this._renderPicker("outdoor_temperature_entity","config_outdoor_temperature_entity",["sensor","weather"],"outdoor_temperature",e,"config_help_outdoor_temperature_entity")}
            ${""}
            ${"calendar"===l?this._renderPicker("tariff_schedule_entity","config_tariff_schedule_entity","schedule",null,e,"config_help_tariff_schedule_entity"):K}
            <div class="stepper-pair">
                ${this._renderStepper("number.sem_cheap_price_threshold","cheap_threshold",t,"setting_help_cheap_threshold")}
                ${this._renderStepper("number.sem_expensive_price_threshold","expensive_threshold",t,"setting_help_expensive_threshold")}
            </div>
            ${""}
            ${this._renderOptionNumberInput("electricity_import_rate","config_import_rate",{min:0,max:1e4,step:.001,unit:`${a}/kWh`,default:.3387},e,"config_help_import_rate")}
            ${""}
            ${this._renderOptionNumberInput("electricity_off_peak_rate","config_off_peak_rate",{min:0,max:1e4,step:.001,unit:`${a}/kWh`,default:e.electricity_nt_rate??e.electricity_import_rate??.3387},e,"config_help_off_peak_rate")}
            ${this._renderOptionNumberInput("electricity_export_rate","config_export_rate",{min:0,max:1e4,step:.001,unit:`${a}/kWh`,default:.075},e,"config_help_export_rate")}
            ${this._renderOptionNumberInput("grid_import_surcharge","config_import_surcharge",{min:0,max:10,step:.001,unit:`${a}/kWh`,default:0},e,"config_help_import_surcharge")}
            ${""}
            ${this._renderValueLayer(e,a)}
            ${this._renderOptionNumberInput("demand_charge_rate","config_demand_charge_rate",{min:0,max:1e5,step:.01,unit:`${a}/kW/Mt`,default:4.32},e,"config_help_demand_charge_rate")}
            ${this._renderPicker("grid_import_power_entity","config_grid_import_entity","sensor","power",e,"config_help_grid_import_entity")}
            ${this._renderPicker("grid_export_power_entity","config_grid_export_entity","sensor","power",e,"config_help_grid_export_entity")}
            ${""}
            ${this._hasBattery()?H`
                ${""}
                ${this._showsControl("battery_setpoint_model")?H`
                <div class="readonly-row" style="margin-top:6px;border-top:1px solid ${t.surfaceBorder};padding-top:8px">
                    <span class="ctrl-label" style="font-weight:600">${this._t("config_battery_control")}</span>
                </div>`:K}
                ${(()=>{const t=this._batteryCount();return t>1?H`${Array.from({length:t},(s,i)=>H`
                            ${this._renderBatteryListPicker("battery_force_discharge_entities","config_force_discharge_entity",["number","input_number"],i,t,e)}
                            ${this._renderBatteryListPicker("battery_strategy_entities","config_strategy_entity",["select","input_select"],i,t,e)}`)}`:H`
                        ${this._renderPicker("battery_force_discharge_control_entity","config_force_discharge_entity","number",null,e,"config_help_force_discharge_entity")}
                        ${this._renderPicker("battery_strategy_control_entity","config_strategy_entity","select",null,e,"config_help_strategy_entity")}
                        ${e.battery_strategy_control_entity?H`
                            ${this._renderTextOption("battery_strategy_active_value","config_strategy_val_active",e,"config_help_strategy_values","api")}
                            ${this._renderTextOption("battery_strategy_idle_value","config_strategy_val_idle",e,"config_help_strategy_values","eco")}
                            ${this._renderTextOption("battery_strategy_self_consume_value","config_strategy_val_selfc",e,"config_help_strategy_values","nom")}
                            ${this._renderTextOption("battery_strategy_off_value","config_strategy_val_off",e,"config_help_strategy_values","idle")}
                        `:K}`})()}
                ${this._renderOptionToggle("battery_setpoint_bidirectional","config_battery_bidirectional",e,"config_help_battery_bidirectional",!1)}
                ${""}
                ${this._renderTextOption("battery_setpoint_model","config_setpoint_model",e,"config_help_setpoint_model","signed")}
                ${"direction_select"===e.battery_setpoint_model?H`
                    ${this._renderPicker("battery_power_direction_entity","config_direction_entity","select",null,e,"config_help_direction_entity")}
                    ${this._renderTextOption("battery_direction_discharge_value","config_direction_val_discharge",e,"config_help_direction_values","discharge")}
                    ${this._renderTextOption("battery_direction_charge_value","config_direction_val_charge",e,"config_help_direction_values","charge")}
                `:K}
            `:K}
            ${""}
        `}_renderHeatPump(t){const e=this._bin("heat_pump_registered"),s=this._options||{},i=(this._hass?.config?.currency||"EUR")+"/kWh",r=e?H`
            <div class="hp-status">
                <div class="readonly-row">
                    <span class="ctrl-label">${this._t("heat_pump_mode")}</span>
                    <span class="readonly-value">${this._valLabel("heat_pump_mode")||"—"}</span>
                </div>
                <div class="readonly-row">
                    <span class="ctrl-label">${this._t("heat_pump_sg_ready_state")}</span>
                    <span class="readonly-value">${this._val("heat_pump_sg_ready_state")||"—"}</span>
                </div>
            </div>
        `:H`
            <div class="setup-intro">
                ${this._t("config_heat_pump_intro")}
            </div>
        `;return H`
            ${r}
            <div class="hp-form">
                ${""}
                ${this._renderPicker("heat_pump_relay1_entity","config_hp_relay1",sa,null,s,"config_help_hp_relay")}
                ${this._isValueContact(s.heat_pump_relay1_entity)?H`
                    ${this._renderOptionTextInput("heat_pump_relay1_on_value","config_hp_relay1_on",s,"config_help_hp_contact_values","100000000000")}
                    ${this._renderOptionTextInput("heat_pump_relay1_off_value","config_hp_relay1_off",s,"config_help_hp_contact_values","000000000000")}`:K}
                ${this._renderPicker("heat_pump_relay2_entity","config_hp_relay2",sa,null,s,"config_help_hp_relay")}
                ${this._isValueContact(s.heat_pump_relay2_entity)?H`
                    ${this._renderOptionTextInput("heat_pump_relay2_on_value","config_hp_relay2_on",s,"config_help_hp_contact_values","100000000000")}
                    ${this._renderOptionTextInput("heat_pump_relay2_off_value","config_hp_relay2_off",s,"config_help_hp_contact_values","000000000000")}`:K}
                ${""}
                ${this._renderOptionToggle("heat_pump_invert_sg_ready","config_hp_invert_sg_ready",s,"config_help_hp_invert_sg_ready",!1)}
                ${this._renderPicker("heat_pump_climate_entity","config_hp_climate","climate",null,s,"config_help_hp_climate")}
                ${this._renderPicker("heat_pump_power_sensor","config_hp_power_sensor","sensor","power",s,"config_help_hp_power_sensor")}
                ${""}
                ${this._renderPicker("heat_pump_energy_sensor","config_hp_energy_sensor","sensor","energy",s,"config_help_hp_energy_sensor")}
                ${""}
                ${this._renderOptionNumberInput("heat_pump_rated_power","config_hp_rated_power",{min:100,max:3e4,step:50,unit:"W",default:2e3},s,"config_help_hp_rated_power")}
                ${""}
                ${this._renderPicker("heat_pump_temperature_sensor","config_hp_temperature_sensor","sensor","temperature",s,"config_help_hp_temperature_sensor")}
                ${""}
                ${this._renderPicker("vacation_mode_entity","config_vacation_entity",["binary_sensor","input_boolean","switch","calendar"],null,s,"config_help_vacation_entity")}
                ${e?this._renderStepper("number.sem_heat_pump_boost_offset","heat_pump_boost_offset",t,"config_help_hp_boost_offset"):this._renderOptionSlider("heat_pump_boost_offset","heat_pump_boost_offset",{min:0,max:10,step:.5,unit:"°C",default:2},s,"config_help_hp_boost_offset")}
                ${this._renderOptionSlider("heat_pump_max_setpoint","config_hp_max_setpoint",{min:30,max:80,step:1,unit:"°C",default:55},s,"config_help_hp_max_setpoint")}
                ${""}
                ${this._renderOptionNumberInput("heat_pump_tariff_rate","device_tariff_rate",{min:0,max:1e4,step:.001,unit:i,default:0},s,"config_help_hp_tariff_rate")}
                ${this._renderPicker("heat_pump_tariff_entity","device_tariff_entity",["sensor","input_number"],null,s,"config_help_hp_tariff_entity")}
                ${this._renderPicker("heat_pump_tariff_meter","device_tariff_meter","sensor","energy",s,"config_help_hp_tariff_meter")}
                ${""}
            </div>
        `}_renderHotWater(t){const e=this._options||{},s=this._bin("hot_water_registered"),i=this._val("hot_water_current_temperature"),r=this._val("hot_water_solar_target"),a=this._val("hot_water_hours_since_legionella"),n=this._bin("hot_water_legionella_cycle_active"),o=this._val("hot_water_temperature_reading_path"),l=this._val("hot_water_temperature_safety_path"),c=this._val("hot_water_activation_path"),d=s?H`
            <div class="hp-status">
                <div class="readonly-row">
                    <span class="ctrl-label">${this._t("hot_water_current_temperature")}</span>
                    <span class="readonly-value">${i?`${parseFloat(i).toFixed(1)} °C`:"—"}</span>
                </div>
                <div class="readonly-row">
                    <span class="ctrl-label">${this._t("hot_water_solar_target")}</span>
                    <span class="readonly-value">${r?`${parseFloat(r).toFixed(0)} °C`:"—"}</span>
                </div>
                <div class="readonly-row">
                    <span class="ctrl-label">${this._t("hot_water_hours_since_legionella")}</span>
                    <span class="readonly-value">${n?this._t("hot_water_legionella_cycle_running"):a&&parseFloat(a)<999?`${parseFloat(a).toFixed(0)} h`:this._t("hot_water_legionella_never_run")}</span>
                </div>
                ${o?H`
                    <div class="readonly-row">
                        <span class="ctrl-label">${this._t("hot_water_temperature_reading_path")}</span>
                        <span class="readonly-value">${o}</span>
                    </div>
                `:K}
                ${l&&"uninitialized"!==l?H`
                    <div class="readonly-row">
                        <span class="ctrl-label">${this._t("hot_water_temperature_safety_path")}</span>
                        <span class="readonly-value">${l}</span>
                    </div>
                `:K}
                ${c&&"uninitialized"!==c?H`
                    <div class="readonly-row">
                        <span class="ctrl-label">${this._t("hot_water_activation_path")}</span>
                        <span class="readonly-value">${c}</span>
                    </div>
                `:K}
            </div>
        `:H`
            <div class="setup-intro">
                ${this._t("config_hot_water_intro")}
            </div>
        `;return H`
            ${d}
            <div class="hp-form">
                ${this._renderPicker("hot_water_entity","config_hw_entity",["switch","input_boolean","water_heater","climate"],null,e,"config_help_hw_entity")}
                ${this._renderPicker("hot_water_temperature_sensor","config_hw_temp_sensor","sensor","temperature",e,"config_help_hw_temp_sensor")}
                ${this._renderPicker("hot_water_power_sensor","config_hw_power_sensor","sensor","power",e,"config_help_hw_power_sensor")}
                ${""}
                ${this._renderPicker("hot_water_energy_sensor","config_hw_energy_sensor","sensor","energy",e,"config_help_hw_energy_sensor")}
                ${""}
                ${this._renderOptionNumberInput("hot_water_rated_power","config_hw_rated_power",{min:100,max:3e4,step:50,unit:"W",default:2500},e,"config_help_hw_rated_power")}
                ${this._renderStepper("number.sem_hot_water_solar_target","hot_water_solar_target",t,"config_help_hw_solar_target")}
                ${this._renderOptionSlider("hot_water_legionella_target","config_hw_legionella_target",{min:55,max:80,step:1,unit:"°C",default:65},e,"config_help_hw_legionella_target")}
                ${""}
                ${""}
            </div>
        `}async _saveChargerField(t,e,s,i,r,a){const n=(a.ev_chargers||[]).map(t=>({...t}));n[t]||(n[t]={}),!n[t].id&&e&&(n[t].id=e),n[t][s]=i,await this._saveOption("ev_chargers",n,r)}async _addSuggestedCharger(t){if(this._chargerBusy)return;const e=this._options.ev_chargers||[],s=function(t,e,s){return t&&t.id?(e||[]).includes(t.id)?{action:"exists",id:t.id}:{action:"add",charger:{...t,ev_min_current:6,ev_surplus_priority:(s||0)+3}}:{action:"none"}}(t,[...e.map(t=>t&&t.id).filter(Boolean),...this._chargersList()],e.length);if("none"!==s.action){this._chargerBusy=!0,this.requestUpdate();try{"add"===s.action&&await this._saveOption("ev_chargers",[s.charger],"ev_chargers_add"),await this._refreshOptions()}finally{this._chargerBusy=!1,this.requestUpdate()}}}_reportNearMissUrl(t){if("report"!==Lr(t))return"";const e=(t.entities||[]).map(t=>`- \`${t.entity}\` (${t.domain}${t.device_class?"/"+t.device_class:""})`).join("\n"),s=["**Detected hardware — no role matched**","",`Integration: ${t.roster?.name?`${t.roster.name} (\`${t.platform}\`)`:`\`${t.platform}\``}`,t.roster?.installs?`Installs (HA analytics): ${t.roster.installs}`:"","","Entities on this device:",e,"","What the device is and which entity does what:","(please fill in)"].filter(Boolean).join("\n");return"https://github.com/traktore-org/sem-community/issues/new?labels=enhancement&title="+encodeURIComponent(`Detected hardware: ${t.platform} — no role matched`)+"&body="+encodeURIComponent(s)}async _addCharger(){if(this._chargerBusy)return;const t=this._options.ev_chargers||[],e=new Set([...t.map(t=>t&&t.id).filter(Boolean),...this._chargersList()]);let s="ev_charger",i=1;for(;e.has(s);)s="ev_charger_"+i++;const r={id:s,name:`${this._t("config_ev_new_charger")} ${t.length+1}`,ev_min_current:6,ev_surplus_priority:t.length+3};this._chargerBusy=!0,this.requestUpdate();try{await this._saveOption("ev_chargers",[r],"ev_chargers_add"),await this._refreshOptions()}finally{this._chargerBusy=!1,this.requestUpdate()}}async _removeCharger(t){if(!this._chargerBusy&&t){this._chargerBusy=!0,this._pendingRemove="",this.requestUpdate();try{await this._hass.callService("solar_energy_management","remove_charger",{charger_id:t}),await this._refreshOptions()}catch(t){console.error("[sem-config-card] remove_charger failed",t)}finally{this._chargerBusy=!1,this.requestUpdate()}}}_extModeOptions(){return[["none","config_ext_ctrl_mode_none"],["yield","config_ext_ctrl_mode_yield"],["observe","config_ext_ctrl_mode_observe"]]}_renderExtModeNested(t,e,s,i){if(!this._gateCharger("external_control_mode"))return K;const r=s.external_control_mode||"none",a=`ev_chargers.${t}.external_control_mode`,n=this._saveStatus[a];return H`
            <div class="stepper-cell">
                <div class="ctrl-row">
                    <span class="ctrl-label">${this._t("config_ext_ctrl_mode")}</span>
                    <select class="sem-select" .value=${r} @change=${s=>this._saveChargerField(t,e,"external_control_mode",s.target.value,a,i)}>
                        ${this._extModeOptions().map(([t,e])=>H`
                            <option value=${t} ?selected=${r===t}>${this._t(e)}</option>`)}
                    </select>
                </div>
                ${"saving"===n?H`<div class="save-status">${this._t("config_saving")}…</div>`:K}
                ${"ok"===n?H`<div class="save-status ok">✓</div>`:K}
                ${this._showHelp?H`<div class="setting-help-text">${this._t("config_help_ext_ctrl")}</div>`:K}
            </div>
        `}_renderExtModeOption(t){if(!this._gate("battery_external_control_mode"))return K;const e=t.battery_external_control_mode||"none",s=this._saveStatus.battery_external_control_mode;return H`
            <div class="stepper-cell">
                <div class="ctrl-row">
                    <span class="ctrl-label">${this._t("config_ext_ctrl_mode")}</span>
                    <select class="sem-select" .value=${e} @change=${t=>this._saveOption("battery_external_control_mode",t.target.value,"battery_external_control_mode")}>
                        ${this._extModeOptions().map(([t,s])=>H`
                            <option value=${t} ?selected=${e===t}>${this._t(s)}</option>`)}
                    </select>
                </div>
                ${"saving"===s?H`<div class="save-status">${this._t("config_saving")}…</div>`:K}
                ${"ok"===s?H`<div class="save-status ok">✓</div>`:K}
                ${this._showHelp?H`<div class="setting-help-text">${this._t("config_help_ext_ctrl")}</div>`:K}
            </div>
        `}_renderTargetTypeSelectNested(t,e,s,i){if(!this._gateCharger("ev_target_type"))return K;const r=s.ev_target_type||"kwh",a=!!s.vehicle_soc_entity,n=`ev_chargers.${t}.ev_target_type`,o=this._saveStatus[n];return H`
            <div class="stepper-cell">
                <div class="ctrl-row">
                    <span class="ctrl-label">${this._t("config_ev_target_type")}</span>
                    <select class="sem-select" .value=${r} @change=${s=>this._saveChargerField(t,e,"ev_target_type",s.target.value,n,i)}>
                        <option value="kwh" ?selected=${"soc"!==r}>
                            ${this._t("config_ev_target_type_kwh")}
                        </option>
                        <option value="soc" ?disabled=${!a}
                                            ?selected=${"soc"===r}>
                            ${this._t("config_ev_target_type_soc")}${a?"":" — "+this._t("config_ev_target_type_requires_sensor")}
                        </option>
                    </select>
                </div>
                ${"saving"===o?H`<div class="save-status">${this._t("config_saving")}…</div>`:K}
                ${"ok"===o?H`<div class="save-status ok">✓</div>`:K}
                ${this._showHelp?H`<div class="setting-help-text">${this._t("config_help_ev_target_type")}</div>`:K}
            </div>
        `}_renderTextNested(t,e,s,i,r,a,n){if(!this._gateCharger(s))return K;const o=r.ev_chargers||[],l=o[t]?.[s]??"",c=`ev_chargers.${t}.${s}`,d=this._saveStatus[c];return H`
            <div class="picker-cell">
                <div class="picker-row">
                    <span class="picker-label">${this._t(i)}</span>
                    <input type="text" class="txt-opt" .value=${String(l)}
                           placeholder="${n||""}"
                           @keydown=${t=>{"Enter"===t.key&&t.target.blur()}}
                           @blur=${i=>{const a=i.target.value.trim();a!==String(l)&&this._saveChargerField(t,e,s,a,c,r)}} />
                </div>
                ${"saving"===d?H`<div class="save-status">${this._t("config_saving")}…</div>`:K}
                ${"ok"===d?H`<div class="save-status ok">✓ ${this._t("config_saved")}</div>`:K}
                ${this._showHelp&&a?H`<div class="setting-help-text">${this._t(a)}</div>`:K}
            </div>
        `}_renderToggleNested(t,e,s,i,r,a){if(!this._gateCharger(s))return K;const n=r.ev_chargers||[],o=!!n[t]?.[s],l=`ev_chargers.${t}.${s}`,c=this._saveStatus[l];return H`
            <div class="picker-cell">
                <div class="toggle-row">
                    <span class="toggle-label">${this._t(i)}${this._helpBtn(a)}</span>
                    <div class="toggle-track ${o?"on":""}"
                         @click=${()=>this._saveChargerField(t,e,s,!o,l,r)}>
                        <div class="toggle-thumb"></div>
                    </div>
                </div>
                ${"saving"===c?H`<div class="save-status">${this._t("config_saving")}…</div>`:K}
                ${"ok"===c?H`<div class="save-status ok">✓ ${this._t("config_saved")}</div>`:K}
                ${this._helpBlock(a)}
            </div>
        `}_roleChip(t,e,s){const i=function(t,e,s){if(!Wr.has(s))return{kind:null,detected:null};const i=Hr(t,e);if(!i||!i.device_id)return{kind:null,detected:null};const r=(i.found||{})[s]||null,a=(i.cleared||[]).includes(s);return Object.prototype.hasOwnProperty.call(i.overrides||{},s)?{kind:"you",detected:r&&r!==i.overrides[s]?r:null}:r&&!a?{kind:"detected",detected:r}:{kind:"none",detected:null}}(this._options,t,e);if(!i.kind)return K;const r="you"===i.kind?this._t("config_role_you"):"none"===i.kind?this._t("config_role_none"):this._t("config_role_detected");return H`
            <span class="src-chip ${i.kind}">${r}</span>
            ${"you"===i.kind&&i.detected?H`
                <span class="src-sub">${this._t("config_role_detected_was")} ${i.detected}<a class="src-use"
                    @click=${()=>s(i.detected)}>${this._t("config_role_use_detected")}</a></span>`:K}`}_renderRoleLegend(t){return function(t,e){const s=Hr(t,e);return Boolean(s&&s.device_id)}(this._options,t)?H`
            <div class="src-legend">${this._t("config_role_legend_lead")}
                <span class="src-chip detected">${this._t("config_role_detected")}</span> ${this._t("config_role_legend_detected")}
                <span class="src-chip you">${this._t("config_role_you")}</span> ${this._t("config_role_legend_you")}</div>`:K}_renderPickerNested(t,e,s,i,r,a,n,o){if(!this._gateCharger(s))return K;const l=n.ev_chargers||[],c=l[t]?.[s]||"",d=`ev_chargers.${t}.${s}`,p=this._saveStatus[d],_=i=>this._saveChargerField(t,e,s,i,d,n);return H`
            <div class="picker-cell">
                <div class="picker-row">
                    <span class="picker-label">${this._t(i)}${this._roleChip(e,s,_)}</span>
                    <ha-entity-picker
                        .hass=${this._hass}
                        .value=${c}
                        .includeDomains=${r?Array.isArray(r)?r:[r]:void 0}
                        .includeDeviceClasses=${a&&!["power","co2_intensity","outdoor_temperature"].includes(a)?[a]:void 0}
                        .entityFilter=${"power"===a?Ir:"co2_intensity"===a?Br:"outdoor_temperature"===a?Or:void 0}
                        .allowCustomEntity=${!1}
                        @value-changed=${t=>_(t.detail?.value||"")}>
                    </ha-entity-picker>
                </div>
                ${"saving"===p?H`<div class="save-status">${this._t("config_saving")}…</div>`:K}
                ${"ok"===p?H`<div class="save-status ok">✓ ${this._t("config_saved")}</div>`:K}
                ${this._showHelp&&o?H`<div class="setting-help-text">${this._t(o)}</div>`:K}
            </div>
        `}_batteryCount(){if(!this._hass)return 0;const t=new Set;for(const e of Object.keys(this._hass.states)){const s=e.match(/^sensor\.sem_battery_(b\d+)_power$/);s&&t.add(s[1])}return t.size}_hasBattery(){return!!this._hass&&(this._batteryCount()>0||("sensor.sem_battery_soc"in this._hass.states||"sensor.sem_battery_power"in this._hass.states))}_renderBatteryListPicker(t,e,s,i,r,a,n){if(!this._gate(t))return K;const o=(Array.isArray(a[t])?a[t]:[])[i]||"",l=`${t}.${i}`,c=this._saveStatus[l];return H`
            <div class="picker-cell">
                <div class="picker-row">
                    <span class="picker-label">${this._t(e)} — B${i+1}</span>
                    <ha-entity-picker
                        .hass=${this._hass}
                        .value=${o}
                        .includeDomains=${s}
                        .allowCustomEntity=${!1}
                        @value-changed=${e=>this._saveListField(t,i,e.detail?.value||"",r)}>
                    </ha-entity-picker>
                </div>
                ${"saving"===c?H`<div class="save-status">${this._t("config_saving")}…</div>`:K}
                ${"ok"===c?H`<div class="save-status ok">✓ ${this._t("config_saved")}</div>`:K}
                ${c&&"saving"!==c&&"ok"!==c?H`<div class="save-status err">⚠ ${c}</div>`:K}
                ${this._showHelp&&n?H`<div class="setting-help-text">${this._t(n)}</div>`:K}
            </div>
        `}async _saveListField(t,e,s,i){const{payload:r,shown:a}=function(t,e,s,i,r){const a=t||{},n=Array.isArray(a.battery_slot_units)?[...a.battery_slot_units]:null,o=Array.isArray(a[e])?[...a[e]]:[];for(;o.length<r;)o.push(null);return o[s]=i||null,{payload:{[e]:{slot:s,value:i||null,battery_slot_units:n}},shown:{[e]:o}}}(this._options,t,e,s,i);await this._saveOptions(r,`${t}.${e}`,a),await this._refreshOptions()}_renderPicker(t,e,s,i,r,a){if(!this._gate(t))return K;const n=this._saveStatus[t],o=ia.has(t);o&&this._regPending(t);const l=o&&Object.prototype.hasOwnProperty.call(this._pending,t),c=l?this._pending[t]:r[t]||"",d=e=>{o?(this._pending={...this._pending,[t]:e||""},this.requestUpdate()):this._saveOption(t,e,t)};return H`
            <div class="picker-cell">
                <div class="picker-row">
                    <span class="picker-label">${this._t(e)}${l?H`<span class="pending-dot" title="${this._t("config_pending_hint")}">●</span>`:K}</span>
                    <ha-entity-picker
                        .hass=${this._hass}
                        .value=${c}
                        .includeDomains=${s?Array.isArray(s)?s:[s]:void 0}
                        .includeDeviceClasses=${i&&!["power","co2_intensity","outdoor_temperature"].includes(i)?[i]:void 0}
                        .entityFilter=${"power"===i?Ir:"co2_intensity"===i?Br:"outdoor_temperature"===i?Or:void 0}
                        .allowCustomEntity=${!1}
                        @value-changed=${t=>d(t.detail?.value||"")}>
                    </ha-entity-picker>
                </div>
                ${"saving"===n?H`<div class="save-status">${this._t("config_saving")}…</div>`:K}
                ${"ok"===n?H`<div class="save-status ok">✓ ${this._t("config_saved")}</div>`:K}
                ${n&&"saving"!==n&&"ok"!==n?H`<div class="save-status err">⚠ ${n}</div>`:K}
                ${this._showHelp&&a?H`<div class="setting-help-text">${this._t(a)}</div>`:K}
            </div>
        `}async _applyPending(){if(!Object.keys(this._pending).length||this._applying||this._secApplying)return;this._applying=!0;const t={...this._saveStatus};delete t._apply,this._saveStatus=t,this.requestUpdate();try{const t=await this._ensureEntryId(),e={...this._pending};await this._hass.callService("solar_energy_management","set_option",{options:e,...t?{entry_id:t}:{}}),this._options={...this._options,...e},this._pending={}}catch(t){console.error("[sem-config-card] apply failed",t),this._saveStatus={...this._saveStatus,_apply:t?.message||"apply failed"}}finally{this._applying=!1,this.requestUpdate()}}_discardPending(){this._pending={},this.requestUpdate()}_renderApplyBar(){const t=Object.keys(this._pending).length;if(!t&&!this._applying)return K;const e=this._saveStatus._apply;return H`
            <div class="apply-bar ${e?"apply-err":""}">
                <span class="apply-msg">
                    ${this._applying?H`<span class="apply-spin"></span>${this._t("config_applying")}`:e?H`⚠ ${e}`:this._t("config_pending_changes").replace(/\{n\}/g,String(t))}
                </span>
                ${this._applying||this._secApplying?K:H`
                    <button class="apply-discard" @click=${()=>this._discardPending()}>${this._t("config_discard")}</button>
                    <button class="apply-btn" @click=${()=>this._applyPending()}>${this._t("config_apply")}</button>
                `}
            </div>
        `}_reg(t){this._sec&&(this._secOf[t]=this._sec)}_liveOf(t,e){if("option"===e){return(this._options||{})[t.slice(4)]}const s=this._hass?.states[t];if(s)return"number"===e?parseFloat(s.state):s.state}_stage(t,e,s){const i=this._liveOf(t,e),r="number"===e?Number(i)===Number(s):String(i)===String(s),a={...this._staged};r?delete a[t]:a[t]={kind:e,value:s},this._staged=a}_isDirty(t){return Object.prototype.hasOwnProperty.call(this._staged,t)}_stagedVal(t,e){const s=this._staged[t];return void 0===s?e:s.value}_sectionStaged(t){return Object.keys(this._staged).filter(e=>this._secOf[e]===t)}_regPending(t){this._reg(Jr+t)}_sectionPending(t){return Object.keys(this._pending).filter(e=>this._secOf[Jr+e]===t)}_sectionUnsaved(t){return this._sectionStaged(t).length+this._sectionPending(t).length}_revertSection(t){const e={...this._staged};this._sectionStaged(t).forEach(t=>delete e[t]),this._staged=e;const s={...this._pending};this._sectionPending(t).forEach(t=>delete s[t]),this._pending=s}async _applySection(t){const e=this._sectionStaged(t),s=this._sectionPending(t);if((e.length||s.length)&&!this._secApplying&&!this._applying){this._secApplying=t;try{const t={};s.forEach(e=>{t[e]=this._pending[e]});for(const s of e){const e=this._staged[s];"option"===e.kind?t[s.slice(4)]=e.value:"number"===e.kind?await this._hass.callService("number","set_value",{entity_id:s,value:Number(e.value)}):"select"===e.kind?await this._hass.callService("select","select_option",{entity_id:s,option:String(e.value)}):"switch"===e.kind&&await this._hass.callService("switch","on"===e.value?"turn_on":"turn_off",{entity_id:s})}if(Object.keys(t).length){const e=await this._ensureEntryId();await this._hass.callService("solar_energy_management","set_option",{options:t,...e?{entry_id:e}:{}}),this._options={...this._options,...t}}const i={...this._staged};e.forEach(t=>delete i[t]),this._staged=i;const r={...this._pending};s.forEach(t=>delete r[t]),this._pending=r}catch(e){console.error("[sem-config-card] section apply failed",e),this._saveStatus={...this._saveStatus,["_sec_"+t]:e?.message||"apply failed"}}finally{this._secApplying="",this.requestUpdate()}}}_helpVisible(t){return!(!t||!this._showHelp&&!this._helpOpen[t])}_helpBtn(t){return t?H`<ha-icon class="row-help-btn ${this._helpOpen[t]?"on":""}"
            icon="mdi:information-outline" style="--mdc-icon-size:14px"
            @click=${e=>{e.stopPropagation(),this._helpOpen={...this._helpOpen,[t]:!this._helpOpen[t]}}}></ha-icon>`:K}_helpBlock(t,e,s,i,r){if(!this._helpVisible(t))return K;const a=null!=e&&""!==e,n=a&&i&&r;return H`<div class="setting-help-text">${this._t(t)}${a?H` <span class="help-default">${this._t("config_default_label")}: ${e}${s?" "+s:""}</span>`:K}${n?H` <button class="help-reset-btn" title="${this._t("config_reset_default")}"
                  @click=${t=>{t.stopPropagation(),this._stage(i,r,e)}}>↺ ${this._t("config_reset_default")}</button>`:K}</div>`}_renderOptionSelect(t,e,s,i,r,a,n){if(!this._gate(t))return K;const o="opt:"+t;this._reg(o);const l=null!=i[t]?i[t]:a,c=this._isDirty(o),d=this._stagedVal(o,l);return H`
            <div class="stepper-cell ${c?"dirty":""}">
                <div class="ctrl-row">
                    <span class="ctrl-label">${this._t(e)}${c?H`<span class="dirty-dot">●</span>`:K}${this._helpBtn(r)}</span>
                    <select class="sem-select"
                            .value=${d}
                            @change=${t=>n?n(t.target.value):this._stage(o,"option",t.target.value)}>
                        ${s.map(t=>H`
                            <option value="${t.value}" ?selected=${t.value===d}>${t.label}</option>
                        `)}
                    </select>
                </div>
                ${this._helpBlock(r,a,void 0,o,"option")}
            </div>
        `}_renderOptionToggle(t,e,s,i,r){if(!this._gate(t))return K;const a=ia.has(t),n="opt:"+t;a?this._regPending(t):this._reg(n);const o=a&&Object.prototype.hasOwnProperty.call(this._pending,t),l=null!=s[t]?!!s[t]:!!r,c=o||!a&&this._isDirty(n),d=o?!!this._pending[t]:!a&&this._isDirty(n)?!!this._staged[n].value:l;return H`
            <div class="stepper-cell ${c?"dirty":""}">
                <div class="toggle-row">
                    <span class="toggle-label">${this._t(e)}${c?H`<span class="dirty-dot" title="${this._t("config_pending_hint")}">●</span>`:K}${this._helpBtn(i)}</span>
                    <div class="toggle-track ${d?"on":""}"
                         @click=${()=>{a?(this._pending={...this._pending,[t]:!d},this.requestUpdate()):this._stage(n,"option",!d)}}>
                        <div class="toggle-thumb"></div>
                    </div>
                </div>
                ${this._helpBlock(i)}
            </div>
        `}_renderOptionNumberInput(t,e,s,i,r){if(!this._gate(t))return K;const a="opt:"+t;this._reg(a);const n=null!=i[t]?i[t]:s.default,o=this._isDirty(a),l=this._stagedVal(a,n),c=t=>{const e=parseFloat(t);if(Number.isNaN(e))return;const i=Math.max(s.min,Math.min(s.max,e));this._stage(a,"option",i)};return H`
            <div class="stepper-cell ${o?"dirty":""} ${s.disabled?"is-disabled":""}">
                <div class="ctrl-row">
                    <span class="ctrl-label">${this._t(e)}${o?H`<span class="dirty-dot">●</span>`:K}${this._helpBtn(r)}</span>
                    <div class="num-input-wrap">
                        <input class="sem-num-input" type="number"
                               ?disabled=${!!s.disabled}
                               .value=${String(l)}
                               min=${s.min} max=${s.max} step=${s.step}
                               @change=${t=>c(t.target.value)}
                               @blur=${t=>c(t.target.value)}
                               @keydown=${t=>{"Enter"===t.key&&t.target.blur()}}>
                        ${s.unit?H`<span class="num-unit">${s.unit}</span>`:K}
                    </div>
                </div>
                ${this._helpBlock(r,s.default,s.unit,a,"option")}
            </div>
        `}_renderOptionTextInput(t,e,s,i,r){if(!this._gate(t))return K;const a="opt:"+t;this._reg(a);const n=null!=s[t]?s[t]:"",o=this._isDirty(a),l=this._stagedVal(a,n);return H`
            <div class="picker-cell ${o?"dirty":""}">
                <div class="picker-row">
                    <span class="picker-label">${this._t(e)}${o?H`<span class="dirty-dot">●</span>`:K}${this._helpBtn(i)}</span>
                    <input type="text" class="txt-opt" .value=${String(l??"")}
                           placeholder="${r||""}"
                           @keydown=${t=>{"Enter"===t.key&&t.target.blur()}}
                           @blur=${t=>{const e=t.target.value.trim();e!==String(l??"")&&this._stage(a,"option",e)}} />
                </div>
                ${this._helpBlock(i,null,null,a,"option")}
            </div>
        `}_renderOptionSlider(t,e,s,i,r){if(!this._gate(t))return K;const a="opt:"+t;this._reg(a);const n=parseFloat(null!=i[t]?i[t]:s.default)||0,o=this._isDirty(a),l=Number(this._stagedVal(a,n)),c=s.step<1?1:0,d=s.unit||"",p=s.max>s.min?Math.round((l-s.min)/(s.max-s.min)*100):0,_=t=>{const e=Math.min(s.max,Math.max(s.min,l+t*s.step));this._stage(a,"option",e)};return H`
            <div class="zone-knob ${o?"dirty":""}">
                <div class="zone-knob-top">
                    <span class="zone-knob-label">${this._t(e)}${this._helpBtn(r)}</span>
                    <span class="zone-chip">${o?H`<span class="dirty-dot">●</span>`:K}${l.toFixed(c)}${d?" "+d:""}</span>
                </div>
                <div class="zone-knob-slider">
                    <button class="zone-mini" @click=${()=>_(-1)}>−</button>
                    <input type="range" class="zone-range"
                        min=${s.min} max=${s.max} step=${s.step} .value=${String(l)}
                        style=${`--fill:${p}%`}
                        @change=${t=>this._stage(a,"option",parseFloat(t.target.value))} />
                    <button class="zone-mini" @click=${()=>_(1)}>+</button>
                </div>
                ${this._helpBlock(r,s.default,d,a,"option")}
            </div>
        `}_renderBatteryScheduler(t){const e=this._options||{};return H`
            <div class="setup-intro">${this._t("config_battery_scheduler_intro")}</div>
            ${this._renderOptionToggle("battery_charge_scheduler_enabled","config_bs_enabled",e,"config_help_bs_enabled",!1)}
            ${this._renderOptionNumberInput("battery_capacity_kwh","config_bs_capacity",{min:1,max:100,step:.5,unit:"kWh",default:10},e,"config_help_bs_capacity")}
            ${this._renderOptionNumberInput("battery_max_charge_power_w","config_bs_max_charge",{min:500,max:25e3,step:100,unit:"W",default:5e3},e,"config_help_bs_max_charge")}
            ${this._renderOptionSlider("battery_roundtrip_efficiency","config_bs_efficiency",{min:.7,max:.99,step:.01,unit:"",default:.92},e,"config_help_bs_efficiency")}
            ${this._renderOptionNumberInput("battery_cycle_cost","config_bs_cycle_cost",{min:0,max:.5,step:.001,unit:"EUR/kWh",default:.02},e,"config_help_bs_cycle_cost")}
            ${this._renderOptionSlider("battery_precharge_trigger_hour","config_bs_trigger_hour",{min:18,max:23,step:1,unit:"h",default:21},e,"config_help_bs_trigger_hour")}
            ${this._renderOptionSlider("battery_replan_interval_min","config_bs_replan_interval",{min:5,max:120,step:5,unit:"min",default:30},e,"config_help_bs_replan_interval")}
            ${this._renderOptionToggle("battery_prefer_consecutive_window","config_bs_block_mode",e,"config_help_bs_block_mode",!0)}
            ${this._renderOptionSlider("battery_max_target_soc","config_bs_max_target_soc",{min:50,max:100,step:5,unit:"%",default:95},e,"config_help_bs_max_target_soc")}
            ${this._renderOptionNumberInput("battery_min_deficit_kwh","config_bs_min_deficit",{min:.5,max:10,step:.5,unit:"kWh",default:2},e,"config_help_bs_min_deficit")}
            ${this._renderOptionSlider("battery_pessimism_weight","config_bs_pessimism",{min:0,max:1,step:.1,unit:"",default:.3},e,"config_help_bs_pessimism")}
            ${this._renderOptionToggle("battery_force_charge_negative_price","config_bs_force_neg",e,"config_help_bs_force_neg",!0)}
        `}_batteryIntelligenceSubtitle(){const t=this._hass?.states?.["sensor.sem_battery_spendable_kwh"],e=t?.attributes?.phase;return e?this._t(`planning_phase_${e}`):""}_renderBatteryIntelligence(t){const e=this._options||{},s="deye"===e.battery_charge_platform;return H`
            ${this._renderToggle("switch.sem_forecast_spending_enabled","forecast_spending",t,"config_help_forecast_spending")}
            ${this._renderToggle("switch.sem_battery_may_export","battery_may_export",t,"config_help_battery_may_export")}
            ${this._renderToggle("switch.sem_battery_may_assist_ev","battery_may_assist_ev",t,"config_help_battery_may_assist_ev")}
            <div style="margin-top:6px;border-top:1px solid ${t.surfaceBorder};padding-top:4px"></div>
            ${this._renderToggle("switch.sem_battery_charge_pacing_enabled","battery_charge_pacing",t,"config_help_battery_charge_pacing")}
            ${this._renderPicker("battery_charge_power_limit_entity","config_charge_power_limit_entity","number",null,e,"config_help_charge_power_limit_entity")}
            ${this._renderOptionNumberInput("inverter_ac_limit_w","config_inverter_ac_limit",{min:0,max:1e5,step:100,unit:"W",default:0},e,"config_help_inverter_ac_limit")}
            ${""}
            <div style="margin-top:6px;border-top:1px solid ${t.surfaceBorder};padding-top:4px"></div>
            ${this._renderToggle("switch.sem_export_guard_enabled","export_guard",t,"config_help_export_guard")}
            ${this._renderStepper("number.sem_export_guard_engage_s","export_guard_engage_s",t,"config_help_export_guard_engage_s")}
            ${this._renderStepper("number.sem_export_guard_release_s","export_guard_release_s",t,"config_help_export_guard_release_s")}
            ${this._renderToggle("switch.sem_export_guard_override_external","export_guard_override",t,"config_help_export_guard_override")}
            ${this._renderToggle("switch.sem_battery_house_sink_enabled","battery_house_sink",t,"config_help_battery_house_sink")}
            ${this._renderToggle("switch.sem_ev_morning_window_enabled","ev_morning_window",t,"config_help_ev_morning_window")}
            ${this._renderStepper("number.sem_ev_morning_window_hours","ev_morning_window_hours",t,"config_help_ev_morning_window_hours")}
            ${this._renderStepper("number.sem_battery_morning_drain_floor_soc","battery_morning_drain_floor_soc",t,"config_help_battery_morning_drain_floor_soc")}
            ${s?H`
                <div style="margin-top:6px;border-top:1px solid ${t.surfaceBorder};padding-top:4px"></div>
                ${this._renderOptionToggle("deye_system_work_mode_control","config_deye_system_work_mode",e,"config_help_deye_system_work_mode",!1)}
                ${this._renderPicker("deye_system_work_mode_entity","config_deye_system_work_mode_entity","select",null,e,"config_help_deye_system_work_mode_entity")}`:K}
        `}_renderLoadManagement(t){const e=this._options||{},s="opt:peak_limit_unlimited",i=this._isDirty(s)?!!this._staged[s].value:!!e.peak_limit_unlimited;return H`
            <div class="readonly-row">
                <span class="ctrl-label">${this._t("load_management_status")}</span>
                <span class="readonly-value">${this._valLabel("load_management_status")||"—"}</span>
            </div>
            ${this._renderOptionToggle("load_management_enabled","config_lm_enabled",e,"config_help_lm_enabled",!1)}
            ${this._renderOptionToggle("peak_limit_unlimited","config_lm_unlimited",e,"config_help_lm_unlimited",!1)}
            ${i?H`
                <div class="readonly-row">
                    <span class="ctrl-label">${this._t("config_lm_target_peak")}</span>
                    <span class="readonly-value">${this._t("config_lm_unlimited_value")}</span>
                </div>
                ${this._renderOperatorRelay(e)}
            `:H`
                ${this._renderOptionNumberInput("target_peak_limit","config_lm_target_peak",{min:1,max:80,step:.1,unit:"kW",default:5},e,"config_help_lm_target_peak")}
                ${this._renderOperatorRelay(e)}
                ${this._showsControl("warning_peak_level")?H`
                <div class="advanced-toggle-row" @click=${()=>{this._lmAdvancedOpen=!this._lmAdvancedOpen}}>
                    <ha-icon class="chevron" icon="mdi:chevron-down"
                             style="--mdc-icon-size:16px;transform:${this._lmAdvancedOpen?"rotate(0deg)":"rotate(-90deg)"}"></ha-icon>
                    <span>${this._t("config_section_advanced")}</span>
                </div>
                ${this._lmAdvancedOpen?H`
                    ${this._renderOptionNumberInput("warning_peak_level","config_lm_warning_peak",{min:1,max:80,step:.1,unit:"kW",default:4.5},e,"config_help_lm_warning_peak")}
                    ${this._renderOptionNumberInput("emergency_peak_level","config_lm_emergency_peak",{min:1,max:80,step:.1,unit:"kW",default:6},e,"config_help_lm_emergency_peak")}
                `:K}`:this._hideRows(2)}
            `}
        `}_renderOperatorRelay(t){const e=t.shed_signal_entity||"";return this._showsControl("shed_signal_entity")?H`
            <div class="operator-relay">
                <div class="operator-relay-head">${this._t("config_shed_signal_heading")}</div>
                ${this._renderPicker("shed_signal_entity","config_shed_signal_entity",["binary_sensor","input_boolean"],null,t,"config_help_shed_signal_entity")}
                ${e?this._renderOptionNumberInput("shed_signal_limit","config_shed_signal_limit",{min:1,max:80,step:.1,unit:"kW",default:4.2},t,"config_help_shed_signal_limit"):K}
            </div>
        `:this._hideRows(e?2:1)}_renderForecast(t){const e=this._val("forecast_source")||"none",s="none"===e?this._t("none"):this._forecastProviderLabel(e),i=this._options||{},r=this._hass?.states?.["sensor.sem_forecast_source"]?.attributes?.sources_available||[],a=t=>!Array.isArray(r)||r.includes(t),n=i.solar_forecast_source||"auto",o=[{value:"auto",label:this._t("config_forecast_source_auto")},...[{value:"solcast",label:"Solcast PV Solar"},{value:"forecast_solar",label:"Forecast.Solar"},{value:"open_meteo",label:"Open-Meteo Solar Forecast"},{value:"helios",label:"Helios Forecast"}].filter(t=>a(t.value)||t.value===n).map(t=>a(t.value)?t:{...t,label:`${t.label} — ${this._t("config_forecast_source_missing")}`})],l=this._hass?.states?.["sensor.sem_forecast_source"]?.attributes||{};return H`
            <div class="readonly-row">
                <span class="ctrl-label">${this._t("forecast_source")}</span>
                <span class="readonly-value">${s}</span>
            </div>
            ${this._renderPlanesToday(l)}
            ${this._renderOptionSelect("solar_forecast_source","config_solar_forecast_source",o,i,"config_help_solar_forecast_source","auto")}
            ${this._renderForecastComparison(l,e)}
            ${"none"===e?H`<div class="overview-help">${this._t("config_forecast_install_hint")}</div>`:K}
        `}_renderForecastComparison(t,e){const s=t.sources_now||{},i=t.source_accuracy||{},r=Object.keys(s);if(r.length<2)return K;const a=t=>null==t?this._t("forecast_still_learning"):`${Math.round(100*Number(t))}%`;return H`
            <div class="readonly-row" style="margin-top:8px">
                <span class="ctrl-label">${this._t("forecast_compare_title")}</span>
            </div>
            <div class="overview-help">${this._t("forecast_compare_help")}</div>
            <table class="sem-planes">
                <tr>
                    <th>${this._t("forecast_compare_source")}</th>
                    <th>${this._t("forecast_compare_today")}</th>
                    <th>${this._t("forecast_compare_accuracy")}</th>
                </tr>
                ${r.map(t=>{const r=s[t]||{},n=i[t]||{},o=Number(n.settled_days||0);return H`
                        <tr class="${t===e?"is-total":""}">
                            <td>
                                ${this._forecastProviderLabel(t)}
                                ${t===e?H`<span style="font-size:10px;opacity:.75;margin-left:6px">${this._t("forecast_in_use")}</span>`:K}
                                ${Number(r.planes||0)>1?H`<span style="font-size:10px;opacity:.6;margin-left:4px">${r.planes}×</span>`:K}
                            </td>
                            <td class="num">${Number(r.today_kwh||0).toFixed(1)} kWh</td>
                            <td class="num" title="${o} ${this._t("forecast_days_of_evidence")}">
                                ${a(n.trust_today)}
                            </td>
                        </tr>`})}
            </table>
        `}_renderPlanesToday(t){const e=t.planes_today||[];if(!Array.isArray(e)||e.length<2)return K;const s=e.reduce((t,e)=>t+Number(e.today_kwh||0),0);return H`
            <table class="sem-planes">
                <tr>
                    <th>${this._t("forecast_per_string_title")}</th>
                    <th>${this._t("forecast_per_string_today")}</th>
                </tr>
                ${e.map(t=>H`
                    <tr>
                        <td>${t.name}</td>
                        <td class="num">${Number(t.today_kwh||0).toFixed(1)} kWh</td>
                    </tr>`)}
                <tr class="is-total">
                    <td>${this._t("forecast_per_string_total").replace("{n}",String(e.length))}</td>
                    <td class="num">${s.toFixed(1)} kWh</td>
                </tr>
            </table>
        `}_pvStrings(){const t=this._hass?.states||{},e=[];for(const s of Object.keys(t)){const i=s.match(/^sensor\.sem_pv_string_(pv\d+)_power$/);if(!i)continue;const r=t[s];!0!==r?.attributes?.restored&&e.push({slot:i[1],power:parseFloat(r.state),displayName:r.attributes?.string_name||i[1].toUpperCase()})}return e.sort((t,e)=>t.slot.localeCompare(e.slot,void 0,{numeric:!0})),e}_pvStringsSubtitle(){const t=this._pvStrings().length;return t?`${t} ${this._t("pv_strings_unit")||"strings"}`:""}_onPvNameInput(t,e){this._pvNameEdits={...this._pvNameEdits||{},[t]:e}}async _savePvNames(){const t={...this._options?.pv_string_names||{}},e=this._pvNameEdits||{};for(const[s,i]of Object.entries(e)){const e=(i||"").trim();e?t[s]=e:delete t[s]}await this._saveOption("pv_string_names",t,"pv_string_names"),this._pvNameEdits={}}_renderPvStrings(t){if(!this._gate("pv_string_names"))return K;const e=this._pvStrings(),s=this._options?.pv_string_names||{},i=this._pvNameEdits||{},r=this._saveStatus?.pv_string_names;return H`
            <div class="setting-help-text">${this._t("config_pv_strings_help")}</div>
            ${e.map(t=>{const e=void 0!==i[t.slot]?i[t.slot]:s[t.slot]||"",r=Number.isFinite(t.power)?`${t.power.toFixed(0)} W`:"";return H`
                    <div class="pv-name-row">
                        <div class="pv-name-meta">
                            <span class="pv-name-slot">${t.slot.toUpperCase()}</span>
                            ${r?H`<span class="pv-name-power">${r}</span>`:K}
                        </div>
                        <input type="text" class="pv-name-input"
                            placeholder=${t.slot.toUpperCase()}
                            .value=${e}
                            @input=${e=>this._onPvNameInput(t.slot,e.target.value)} />
                    </div>`})}
            <div class="section-footer">
                ${"ok"===r?H`<span class="pv-save-ok">✓</span>`:K}
                <button class="pv-save-btn" ?disabled=${"saving"===r}
                        @click=${()=>this._savePvNames()}>
                    ${"saving"===r?"…":this._t("config_pv_strings_save")}
                </button>
            </div>
        `}_renderNotifications(t){const e=this._options||{},s=[{value:"",label:this._t("config_notif_none")}],i=this._hass?.services||{};for(const t of Object.keys(i.notify||{}))s.push({value:t,label:`notify.${t}`});for(const t of Object.keys(i.rest_command||{}))s.push({value:t,label:`rest_command.${t}`});return H`
            <div class="setup-intro">${this._t("config_notifications_intro")}</div>
            ${this._renderOptionToggle("enable_charger_notifications","config_notif_charger",e,"config_help_notif_charger",!0)}
            ${this._renderOptionToggle("enable_mobile_notifications","config_notif_mobile",e,"config_help_notif_mobile",!1)}
            ${this._renderOptionSelect("mobile_notification_service","config_notif_service",s,e,"config_help_notif_service","")}
            ${""}
            ${this._renderSelect("select.sem_hints","hints",t,"config_help_hints")}
        `}_renderAdvanced(t){const e=this._options||{};return H`
            ${""}
            <div class="readonly-row" style="border-bottom:1px solid ${t.surfaceBorder};padding-bottom:4px;margin-bottom:4px">
                <span class="ctrl-label" style="font-weight:600">${this._t("config_vpp_section")}</span>
            </div>
            ${this._renderOptionToggle("vpp_enabled","config_vpp_enabled",e,"config_help_vpp_enabled",!1)}
            ${this._renderOptionToggle("vpp_observer_mode","config_vpp_observer",e,"config_help_vpp_observer",!0)}
            ${this._renderPicker("vpp_event_active_entity","config_vpp_event_entity",["binary_sensor","sensor"],null,e,"config_help_vpp_event_active_entity")}
            ${this._renderPicker("vpp_direction_entity","config_vpp_direction_entity",["sensor","select","input_select"],null,e,"config_help_vpp_direction_entity")}
            ${this._renderPicker("vpp_event_end_entity","config_vpp_event_end_entity","sensor","timestamp",e,"config_help_vpp_event_end_entity")}
            ${this._renderPicker("vpp_pre_event_entity","config_vpp_pre_event_entity",["binary_sensor","sensor"],null,e,"config_help_vpp_pre_event_entity")}
            ${this._renderOptionSlider("vpp_reserve_soc","config_vpp_reserve_soc",{min:5,max:80,step:5,unit:"%",default:20},e,"config_help_vpp_reserve_soc")}
            <div style="margin-top:6px;border-top:1px solid ${t.surfaceBorder};padding-top:4px"></div>
            ${this._renderToggle("switch.sem_observer_mode","observer_mode",t,"config_help_observer_mode")}
            ${this._renderToggle("switch.sem_simulation_tab","simulation_tab",t,"config_help_simulation_tab")}
            <div class="stepper-pair">
                ${this._renderStepper("number.sem_update_interval","update_interval",t,"config_help_update_interval")}
                ${this._renderStepper("number.sem_minimum_solar_power","min_solar_power",t,"config_help_min_solar_power")}
            </div>
            <div class="stepper-pair">
                ${this._renderStepper("number.sem_regulation_offset","regulation_offset",t,"config_help_regulation_offset")}
                ${this._renderStepper("number.sem_ev_enable_delay_seconds","ev_enable_delay",t,"config_help_ev_enable_delay")}
            </div>
            <div class="stepper-pair">
                ${this._renderStepper("number.sem_ev_disable_delay_seconds","ev_disable_delay",t,"config_help_ev_disable_delay")}
            </div>
            ${this._renderRetention(t)}
            ${this._renderGridSignFix(t)}
        `}_renderRetention(t){const e=this._options||{};return H`
            <div style="margin-top:6px;border-top:1px solid ${t.surfaceBorder};padding-top:4px"></div>
            ${this._renderOptionSlider("status_retention_days","config_retention_label",{min:0,max:14,step:1,unit:" "+this._t("config_retention_unit_days"),default:0},e,"config_help_retention")}
            ${this._gate("status_retention_cleanup")?H`<div class="action-row">
                <button class="action-btn" ?disabled=${this._retentionBusy}
                        @click=${()=>this._purgeStatusHistory()}>
                    ${this._t("config_retention_cleanup")}
                </button>
                <span class="readonly-value">${this._retentionMsg||""}</span>
            </div>`:K}
        `}async _purgeStatusHistory(){this._retentionBusy=!0,this.requestUpdate();try{await this._hass.callService("solar_energy_management","purge_status_history",{}),this._retentionMsg="OK"}catch(t){this._retentionMsg=String(t&&t.message?t.message:t).slice(0,60)}this._retentionBusy=!1,this.requestUpdate()}_renderGridSignFix(t){if(!this._gate("grid_sign_fix"))return K;const e=this._valLabel("diag_grid_sign")||"—",s=this._valLabel("diag_battery_sign")||"—";return H`
            <div class="grid-sign-block">
                <div class="readonly-row">
                    <span class="ctrl-label">${this._t("grid_sign")}</span>
                    <span class="readonly-value">${e}</span>
                </div>
                <div class="action-row">
                    <button class="action-btn" ?disabled=${this._signBusy}
                            @click=${()=>this._flipGridSign()}>
                        <ha-icon icon="mdi:swap-vertical-bold" style="--mdc-icon-size:16px"></ha-icon>
                        ${this._t("fix_grid_sign")}
                    </button>
                    <button class="action-btn action-btn-ghost"
                            @click=${()=>this._resetSignDetection()}>
                        ${this._t("reset_sign_detection")}
                    </button>
                </div>
                ${this._signMsg?H`<div class="sign-feedback">${this._signMsg}</div>`:K}
                ${this._showHelp?H`<div class="setting-help-text">${this._t("fix_grid_sign_help")}</div>`:K}
                <div class="readonly-row" style="margin-top:8px">
                    <span class="ctrl-label">${this._t("battery_sign")}</span>
                    <span class="readonly-value">${s}</span>
                </div>
                <div class="action-row">
                    <button class="action-btn" ?disabled=${this._battSignBusy}
                            @click=${()=>this._flipBatterySign()}>
                        <ha-icon icon="mdi:swap-vertical-bold" style="--mdc-icon-size:16px"></ha-icon>
                        ${this._t("fix_battery_sign")}
                    </button>
                </div>
                ${this._battSignMsg?H`<div class="sign-feedback">${this._battSignMsg}</div>`:K}
                ${this._showHelp?H`<div class="setting-help-text">${this._t("fix_battery_sign_help")}</div>`:K}
            </div>
        `}_resetSignDetection(){this._hass&&(this._hass.callService("solar_energy_management","reset_sign_detection",{}),this._signMsg=this._t("sign_relearn_started"),this.requestUpdate(),setTimeout(()=>{this._signMsg="",this.requestUpdate()},4e3))}async _flipGridSign(){if(!this._hass||this._signBusy)return;this._signBusy=!0,this._signMsg="",this.requestUpdate();let t=null;try{const e=await this._hass.callService("solar_energy_management","flip_grid_sign",{},void 0,!1,!0);t=e&&e.response?e.response:e}catch(e){t=null}const e=this._buildSignReport(t);let s=!1;try{await navigator.clipboard.writeText(e),s=!0}catch(t){s=!1}this._signBusy=!1,this._signMsg=s?this._t("sign_flipped_copied"):this._t("sign_flipped"),this.requestUpdate(),setTimeout(()=>{this._signMsg="",this.requestUpdate()},6e3)}async _flipBatterySign(){if(!this._hass||this._battSignBusy)return;this._battSignBusy=!0,this._battSignMsg="",this.requestUpdate();let t=null;try{const e=await this._hass.callService("solar_energy_management","flip_battery_sign",{},void 0,!1,!0);t=e&&e.response?e.response:e}catch(e){t=null}const e=this._buildBatterySignReport(t);let s=!1;try{await navigator.clipboard.writeText(e),s=!0}catch(t){s=!1}this._battSignBusy=!1,this._battSignMsg=s?this._t("sign_flipped_copied"):this._t("sign_flipped"),this.requestUpdate(),setTimeout(()=>{this._battSignMsg="",this.requestUpdate()},6e3)}_buildBatterySignReport(t){const e=t&&t.diagnostics||{},s=t&&"boolean"==typeof t.user_flip?String(t.user_flip):"?",i=t=>null==t?"?":String(t),r=t=>Array.isArray(t)&&t.length?t.join(", "):"(none)",a=String.fromCharCode(96),n=t=>a+t+a,o=e.per_bid||{},l=Object.entries(o).map(([t,e])=>"  "+t+": "+i(e.inverted?"negated":"normal")+" (detected="+i(e.detected)+", confidence="+i(e.confidence)+", samples="+i(e.samples)+")");return["### SEM battery-sign report (#588)","","I tapped **Fix battery sign** in the Configuration tab.","battery_sign_user_flip is now "+n(s)+".","","- Battery sensor: "+n(i(e.battery_power_sensor))+" = "+i(e.battery_power_raw_state)+" (raw)","- Battery integration: "+i(e.battery_platform)+" (brand-seeded: "+i(e.brand_seeded)+")","- Per-battery sign state:",...l,"- Charge counters: "+r(e.charge_counters),"- Discharge counters: "+r(e.discharge_counters),"","My hardware (please fill in): inverter / battery brand.","After the flip, does battery charge/discharge show the correct direction?"].join("\n")}_buildSignReport(t){const e=t&&t.diagnostics||{},s=t&&"boolean"==typeof t.user_flip?String(t.user_flip):"?",i=t=>null==t?"?":String(t),r=t=>Array.isArray(t)&&t.length?t.join(", "):"(none)",a=String.fromCharCode(96),n=t=>a+t+a;return["### SEM grid-sign report (#461)","","I tapped **Fix grid sign** in the Configuration tab.","grid_sign_user_flip is now "+n(s)+".","","- Meter sensor: "+n(i(e.grid_power_sensor))+" = "+i(e.grid_power_raw_state)+" (raw)","- Meter integration: "+i(e.grid_platform)+" (brand-seeded: "+i(e.brand_seeded)+")","- Auto-detect: detected="+i(e.auto_detected)+", inverted="+i(e.auto_inverted),"- Manual grid_sign_invert: "+i(e.manual_grid_sign_invert),"- Counter correlation: confidence="+i(e.confidence)+", evidence="+i(e.evidence)+", samples="+i(e.samples),"- Solar correlation: confidence="+i(e.solar_confidence)+", evidence="+i(e.solar_evidence)+", samples="+i(e.solar_samples),"- Seen import="+i(e.seen_import)+", export="+i(e.seen_export),"- Import counters: "+r(e.import_counters),"- Export counters: "+r(e.export_counters),"","My hardware (please fill in): inverter / grid meter / battery brand.","After the flip, do the Home-tab import vs export arrows now point the right way?"].join("\n")}_renderSectionHeader(t,e){const s=this._collapsed[t.id]?"rotate(-90deg)":"rotate(0deg)",i=t.subtitleFn(this),r="overview"===t.id?"all":t.id;return H`
            <div class="section-header" @click=${()=>this._toggleSection(t.id)}>
                <div class="section-dot" style="background:${t.color}"></div>
                <ha-icon icon="${t.icon}" style="--mdc-icon-size:20px;color:${t.color}"></ha-icon>
                <span class="section-title-text">${this._t(t.titleKey)}</span>
                ${this._sectionUnsaved(t.id)?H`
                    <span class="header-dirty-badge" title="${this._t("config_pending_hint")}">● ${this._sectionUnsaved(t.id)}</span>`:K}
                ${t.docs?H`
                    <a class="section-docs-link" href="${t.docs}" target="_blank" rel="noopener"
                       title="${this._t("config_docs")}" @click=${t=>t.stopPropagation()}>
                        <ha-icon icon="mdi:book-open-variant" style="--mdc-icon-size:15px"></ha-icon>
                    </a>`:K}
                <span class="section-subtitle" style="color:${i?t.color:""}">${i}</span>
                <sem-diagnose-button
                    .hass=${this._hass}
                    section="${r}"
                    label="${this._t("config_diagnose")}"
                    @click=${t=>t.stopPropagation()}>
                </sem-diagnose-button>
                <ha-icon class="chevron" icon="mdi:chevron-down"
                         style="--mdc-icon-size:18px;transform:${s}"></ha-icon>
            </div>
        `}_renderSection(t,e,s){const i=this._collapsed[t.id];this._sec=t.id,this._rows={shown:0,hidden:0};const r=e(s),a=this._rows;this._rows=null,this._sec=null;const n=this._sectionUnsaved(t.id),o=this._secApplying===t.id||this._applying,l=this._saveStatus["_sec_"+t.id],c=n?H`
            <div class="section-stage-bar">
                <span class="stage-count">● ${n} ${this._t("config_unsaved")}</span>
                ${l?H`<span class="stage-err">⚠ ${l}</span>`:K}
                <button class="stage-btn revert" ?disabled=${o}
                        @click=${()=>this._revertSection(t.id)}>↩ ${this._t("config_revert")}</button>
                <button class="stage-btn apply" ?disabled=${o}
                        @click=${()=>this._applySection(t.id)}>${o?H`${this._t("config_saving")}…`:H`✓ ${this._t("config_apply_section")}`}</button>
            </div>`:K;return H`
            <div class="section ${i?"":"expanded"}"
                 style="--section-accent: ${t.color}">
                ${this._renderSectionHeader(t,s)}
                <div class="section-content ${i?"":"expanded"}">
                    <div class="section-body">
                        ${r}
                        ${this._renderEverydayMore(a)}
                        ${c}
                    </div>
                </div>
            </div>
        `}_renderEverydayMore(t){return!this._advanced&&t&&t.hidden?H`
            <div class="everyday-more">
                ${t.shown?K:H`
                    <span class="everyday-summary">${this._t("config_everyday_nothing_here")}</span>`}
                <button class="everyday-more-btn" @click=${()=>this._setView(!0)}>
                    ${this._t("config_more_in_all").replace(/\{n\}/g,String(t.hidden))}
                </button>
            </div>`:K}_sectionNeedsAttention(t){return!!(this._sectionUnsaved(t)||this._saveStatus["_sec_"+t]||this._revealed.has(t))}_renderGroups(t,e){const s=Object.fromEntries(Qr.map(t=>[t.id,t]));return Xr.map(i=>{const r=i.sections.map(t=>s[t]).filter(Boolean).filter(t=>"pv_strings"!==t.id||this._pvStrings().length>=2),a=i.folds?r.filter(t=>this._advanced||this._sectionNeedsAttention(t.id)):r.filter(t=>this._advanced||Kr.has(t.id)||this._sectionConfigured(t.id)||this._revealed.has(t.id)),n=r.length-a.length;return a.length||i.folds&&n?H`
                <div class="group-heading">${this._t(i.titleKey)}</div>
                ${a.map(s=>this._renderSection(s,t[s.id],e))}
                ${i.folds&&n?H`
                    <button class="group-folded" @click=${()=>this._setView(!0)}>
                        ${this._t("config_finetuning_folded").replace(/\{n\}/g,String(n))}
                    </button>`:K}
            `:K})}render(){if(!this._config)return K;const t=this._theme(),e=!1!==t.isDark,s=t.accent||"#42a5f5",i={overview:t=>this._renderOverview(t),sensor_sources:t=>this._renderSensorSources(t),detected_hardware:t=>this._renderDetectedHardware(t),ev_chargers:t=>this._renderEvChargers(t),battery_zones:t=>this._renderBatteryZones(t),tariff:t=>this._renderTariff(t),heat_pump:t=>this._renderHeatPump(t),hot_water:t=>this._renderHotWater(t),battery_scheduler:t=>this._renderBatteryScheduler(t),battery_intelligence:t=>this._renderBatteryIntelligence(t),load_management:t=>this._renderLoadManagement(t),forecast:t=>this._renderForecast(t),pv_strings:t=>this._renderPvStrings(t),notifications:t=>this._renderNotifications(t),advanced:t=>this._renderAdvanced(t)};return H`
            <style>
                :host { display: block; contain: layout style paint; }
                .wrap {
                    padding: 16px 20px;
                    position: relative;
                    background: ${vt(t,"#8DC892")};
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${t.text});
                }
                .card-help-bar {
                    display: flex; justify-content: space-between;
                    align-items: center; gap: 8px; flex-wrap: wrap;
                    margin: -4px 0 6px;
                }
                /* (#830) Everyday | All settings — one switch, two states. */
                .view-switch {
                    display: inline-flex; padding: 2px; gap: 2px;
                    border-radius: 16px; border: 1px solid ${t.surfaceBorder};
                    background: ${t.surface};
                }
                .view-opt {
                    border: none; background: transparent; cursor: pointer;
                    padding: 4px 12px; border-radius: 14px;
                    font-size: 12px; font-family: inherit;
                    color: ${t.textDim||"rgba(150,160,175,0.9)"};
                    transition: background 0.15s, color 0.15s;
                }
                .view-opt:hover { color: ${s}; }
                .view-opt.on {
                    background: color-mix(in srgb, ${s} 18%, transparent);
                    color: ${s}; font-weight: 600;
                }
                .group-heading {
                    margin: 14px 2px 6px; font-size: 11px; font-weight: 700;
                    text-transform: uppercase; letter-spacing: 0.08em;
                    color: var(--secondary-text-color, ${t.textSec});
                }
                .group-folded, .everyday-more-btn {
                    border: 1px dashed ${t.surfaceBorder}; background: transparent;
                    color: var(--secondary-text-color, ${t.textSec});
                    font-size: 12.5px; font-family: inherit; cursor: pointer;
                    border-radius: 10px; transition: color 0.15s, border-color 0.15s;
                }
                .group-folded {
                    display: block; width: 100%; text-align: left;
                    padding: 10px 14px; margin-bottom: 12px;
                }
                .everyday-more {
                    display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
                    margin-top: 8px;
                }
                .everyday-summary {
                    flex: 1; font-size: 12.5px;
                    color: var(--secondary-text-color, ${t.textSec});
                }
                .everyday-more-btn { padding: 5px 12px; }
                .group-folded:hover, .everyday-more-btn:hover {
                    color: ${s}; border-color: ${s};
                }
                .help-toggle {
                    cursor: pointer;
                    color: var(--secondary-text-color, ${t.textSec});
                    opacity: 0.6;
                    flex-shrink: 0;
                    transition: opacity 0.15s, color 0.15s;
                    user-select: none;
                    padding: 4px;
                    border-radius: 50%;
                }
                .help-toggle:hover { opacity: 1; }
                .help-toggle-labeled {
                    display: inline-flex; align-items: center; gap: 5px;
                    padding: 4px 10px; border-radius: 14px;
                    border: 1px solid ${t.surfaceBorder};
                    font-size: 12px; cursor: pointer;
                    color: ${t.textDim||"rgba(150,160,175,0.9)"};
                    transition: color 0.15s, border-color 0.15s;
                }
                .help-toggle-labeled:hover { color: ${s}; border-color: ${s}; }
                .help-toggle-labeled.on { color: ${s}; border-color: ${s}; }
                .help-toggle.on { color: ${s}; opacity: 1; }

                /* ── Sections: same surface shape as the battery card's
                       per-battery sections (.battery-section) so the
                       Config tab reads like the Battery tab. ── */
                .section {
                    margin-bottom: 12px;
                    border-radius: 12px;
                    background: ${t.surface};
                    border: 1px solid ${t.surfaceBorder};
                    overflow: hidden;
                    transition: border-color 0.3s cubic-bezier(0.4,0,0.2,1), box-shadow 0.2s;
                    position: relative;
                }
                .section.expanded {
                    border-color: color-mix(in srgb, var(--section-accent) 40%, ${t.surfaceBorder});
                    box-shadow: inset 3px 0 0 0 var(--section-accent);
                }
                .section:hover { border-color: ${e?"rgba(255,255,255,0.18)":"rgba(0,0,0,0.12)"}; }
                .section-header {
                    display: flex; align-items: center; gap: 8px;
                    padding: 12px 14px; cursor: pointer; user-select: none;
                    transition: background 0.15s;
                }
                .section.expanded .section-header {
                    background: color-mix(in srgb, var(--section-accent) 6%, transparent);
                }
                .section-dot {
                    width: 8px; height: 8px;
                    border-radius: 50%;
                    flex-shrink: 0;
                }
                .section-title-text {
                    font-size: 0.95em; font-weight: 600; white-space: nowrap;
                    color: var(--primary-text-color, ${t.text});
                }
                .section-subtitle {
                    flex: 1; font-size: 0.75em; font-weight: 500;
                    text-transform: uppercase; letter-spacing: 0.05em;
                    color: var(--secondary-text-color, ${t.textSec});
                    text-align: right; white-space: nowrap;
                    overflow: hidden; text-overflow: ellipsis; margin-right: 4px;
                }
                .chevron { transition: transform 0.25s ease; color: var(--secondary-text-color, ${t.textSec}); }
                /* (#717) inline sub-disclosure for the warning/emergency
                   ladder — most users never touch it, the target slider on
                   the Control tab is the one live control that matters. */
                .advanced-toggle-row {
                    display: flex; align-items: center; gap: 6px;
                    padding: 8px 2px; margin-top: 2px; cursor: pointer; user-select: none;
                    font-size: 0.85em; font-weight: 600;
                    color: var(--secondary-text-color, ${t.textSec});
                }
                .advanced-toggle-row:hover { color: var(--primary-text-color, ${t.text}); }
                .section-content {
                    max-height: 0; opacity: 0; overflow: hidden;
                    transition: max-height 0.3s ease, opacity 0.2s ease;
                }
                .section-content.expanded { max-height: 2000px; opacity: 1; }
                .section-body { padding: 0 14px 14px; }
                .section-footer { display: flex; justify-content: flex-end; align-items: center; gap: 10px; margin-top: 10px; }

                /* (#566) PV-string rename rows */
                .pv-name-row {
                    display: flex; align-items: center; gap: 12px;
                    padding: 8px 0;
                }
                .pv-name-meta {
                    display: flex; flex-direction: column; min-width: 64px;
                }
                .pv-name-slot { font-size: 0.9em; font-weight: 700; color: #ff9800; }
                .pv-name-power {
                    font-size: 0.7em; color: var(--secondary-text-color, ${t.textSec});
                }
                .txt-opt {
                background: rgba(255, 255, 255, 0.06);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 6px;
                color: var(--primary-text-color, #e1e1e1);
                font-size: 12px;
                padding: 3px 8px;
                width: 110px;
            }
            .sv { font-size: 11px; }
            .sv.ok { color: #8DC892; }
            .sv.err { color: #f06292; }
            .pv-name-input {
                    flex: 1; min-width: 0;
                    background: var(--secondary-background-color, ${t.surface});
                    border: 1px solid var(--divider-color, ${t.surfaceBorder});
                    border-radius: 8px; padding: 8px 10px;
                    color: var(--primary-text-color, ${t.text});
                    font-family: inherit; font-size: 0.9em;
                }
                .pv-name-input:focus { outline: none; border-color: #ff9800; }
                .pv-save-btn {
                    background: #ff9800; color: #1a1a1a; border: none;
                    border-radius: 8px; padding: 7px 16px; cursor: pointer;
                    font-weight: 600; font-size: 0.85em;
                }
                .pv-save-btn:disabled { opacity: 0.6; cursor: default; }
                .pv-save-ok { color: #8DC892; font-weight: 700; }

                /* Overview chips — same shape as the battery card's
                   daily chips (.chip / .chip-label / .chip-value). */
                .chips { display: flex; gap: 8px; margin: 6px 0; flex-wrap: wrap; }
                .chip {
                    flex: 1; min-width: 80px;
                    background: var(--secondary-background-color, ${t.surface});
                    border: 1px solid var(--divider-color, ${t.surfaceBorder});
                    border-radius: 10px; padding: 8px 10px; text-align: center;
                    transition: border-color 0.3s cubic-bezier(0.4,0,0.2,1);
                }
                .chip:hover { border-color: var(--divider-color, ${t.surfaceHover}); }
                .chip-label {
                    font-size: 10px; color: var(--secondary-text-color, ${t.textSec});
                    font-weight: 500; letter-spacing: 0.3px; margin: 3px 0;
                }
                .chip-value { font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }
                .c-ok { color: #8DC892; }
                .c-warn { color: #ff9800; }
                .overview-help { font-size: 12px; color: var(--secondary-text-color, ${t.textSec}); padding: 4px 0; }
                /* (#841) Per-string forecast. Tabular numerals so the kWh
                   column reads as a column, not as ragged text. */
                .sem-planes { width: 100%; border-collapse: collapse; font-size: 12px; margin: 2px 0 6px; }
                .sem-planes th { text-align: left; font-weight: 500; padding: 3px 6px 3px 0;
                    color: var(--secondary-text-color, ${t.textSec}); text-transform: uppercase;
                    letter-spacing: .04em; font-size: 10px; }
                .sem-planes td { padding: 3px 6px 3px 0;
                    border-top: 1px solid var(--divider-color, rgba(127,127,127,.2)); }
                .sem-planes td.num { text-align: right; font-variant-numeric: tabular-nums; }
                .sem-planes tr.is-total td { font-weight: 600;
                    border-top: 1px solid var(--primary-text-color, ${t.text}); }
                .overview-actions { display: flex; gap: 8px; margin-top: 10px; }

                .empty-state {
                    display: flex; flex-direction: column; align-items: center;
                    gap: 8px; padding: 16px 8px; text-align: center;
                }
                .empty-title { font-size: 14px; font-weight: 600; color: var(--primary-text-color, ${t.text}); }
                .empty-help {
                    font-size: 12px; color: var(--secondary-text-color, ${t.textSec});
                    max-width: 320px; line-height: 1.4;
                }
                .info-box-text { font-size: 13px; color: var(--secondary-text-color, ${t.textSec}); padding: 6px 0; line-height: 1.4; }

                /* Inline edit primitives (same look as Control card) */
                .ctrl-row { display: flex; align-items: center; justify-content: space-between; padding: 8px 0; }
                .ctrl-label { font-size: 14px; font-weight: 500; }
                .sem-select {
                    background: ${t.surface};
                    border: 1px solid ${t.surfaceBorder};
                    border-radius: 8px;
                    color: var(--primary-text-color, ${t.text});
                    padding: 6px 10px; font-size: 14px; font-family: inherit;
                    cursor: pointer; min-width: 120px; outline: none;
                }
                .sem-select option { background: ${e?"#1e232d":"#fff"}; color: ${e?"#e0e0e0":"#333"}; }
                .stepper-row { display: flex; align-items: center; justify-content: space-between; padding: 7px 0; }
                .stepper-label {
                    font-size: 14px; font-weight: 500; flex: 1; min-width: 0;
                    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
                }
                .stepper-controls { display: flex; align-items: center; gap: 2px; flex-shrink: 0; }
                .stepper-minus, .stepper-plus {
                    width: 30px; height: 30px; border-radius: 8px;
                    border: 1px solid ${t.surfaceBorder};
                    background: ${t.surface}; color: var(--primary-text-color, ${t.text});
                    font-size: 16px; font-weight: 600; cursor: pointer;
                    display: flex; align-items: center; justify-content: center;
                    transition: background 0.15s, border-color 0.15s; user-select: none;
                    padding: 0; line-height: 1;
                }
                .stepper-minus:hover, .stepper-plus:hover { background: ${t.surfaceHover}; border-color: ${s}; }
                .stepper-value {
                    font-size: 14px; font-weight: 600; min-width: 60px; text-align: center;
                    font-variant-numeric: tabular-nums;
                }
                .stepper-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
                @media (max-width: 480px) { .stepper-pair { grid-template-columns: 1fr; } }
                .readonly-row { display: flex; align-items: center; justify-content: space-between; padding: 7px 0; }
                .readonly-row .ctrl-label { font-size: 12px; color: var(--secondary-text-color, ${t.textSec}); font-weight: 500; }
                .readonly-value {
                    font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${t.text});
                }
                /* #461 grid-sign fix block */
                .grid-sign-block { margin-top: 6px; padding-top: 8px; border-top: 1px solid ${t.surfaceBorder}; }
                .grid-sign-block.source-check { margin-top: 0; padding-top: 0; border-top: none; }
                .grid-sign-block .action-row { display: flex; justify-content: flex-end; gap: 8px; padding: 6px 0 2px; }
                .grid-sign-block .action-btn {
                    display: inline-flex; align-items: center; gap: 6px;
                    padding: 7px 14px; border-radius: 9px; cursor: pointer;
                    font-size: 13px; font-weight: 600;
                    color: var(--primary-text-color, ${t.text});
                    background: var(--secondary-background-color, rgba(255,255,255,0.07));
                    border: 1px solid var(--divider-color, ${t.surfaceBorder});
                    transition: background 0.15s;
                }
                .grid-sign-block .action-btn:hover { background: rgba(255,255,255,0.13); }
                .grid-sign-block .action-btn[disabled] { opacity: 0.5; cursor: default; }
                .grid-sign-block .action-btn-ghost {
                    background: transparent; font-weight: 500;
                    color: var(--secondary-text-color, ${t.textSec});
                }
                .grid-sign-block .sign-feedback {
                    text-align: right; font-size: 12px; padding: 4px 0 2px;
                    color: var(--secondary-text-color, ${t.textSec});
                }
                .tariff-rate-row { gap: 8px; border-bottom: 1px solid ${t.surfaceBorder}; margin-bottom: 8px; padding-bottom: 10px; }
                .tariff-rate-value { font-size: 15px; font-weight: 700; color: ${t.text}; }
                .toggle-row { display: flex; align-items: center; justify-content: space-between; padding: 8px 0; }
                .toggle-label { font-size: 14px; font-weight: 500; }
                .toggle-track {
                    position: relative; width: 42px; height: 24px;
                    border-radius: 12px;
                    background: ${e?"rgba(255,255,255,0.15)":"rgba(0,0,0,0.18)"};
                    cursor: pointer; transition: background 0.2s; flex-shrink: 0;
                }
                .toggle-track.on { background: ${s}; }
                .toggle-thumb {
                    position: absolute; top: 2px; left: 2px;
                    width: 20px; height: 20px; border-radius: 50%;
                    background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.3);
                    transition: left 0.2s;
                }
                .toggle-track.on .toggle-thumb { left: 20px; }

                .stepper-cell { display: flex; flex-direction: column; }

                /* ── #528: colorful zone controls (battery design language) ── */
                .zone-knob { padding: 8px 2px 10px; }
                .zone-knob-top {
                    display: flex; align-items: center; justify-content: space-between;
                    margin-bottom: 7px;
                }
                .zone-knob-label { font-size: 14px; font-weight: 600; }
                .zone-chip {
                    background: color-mix(in srgb, var(--section-accent) 18%, transparent);
                    color: var(--section-accent);
                    font-weight: 700; font-size: 0.92em;
                    padding: 2px 11px; border-radius: 11px;
                    border: 1px solid color-mix(in srgb, var(--section-accent) 40%, transparent);
                    min-width: 56px; text-align: center;
                }
                .zone-knob-slider { display: flex; align-items: center; gap: 10px; }
                .zone-mini {
                    width: 28px; height: 28px; flex-shrink: 0;
                    border-radius: 8px; cursor: pointer;
                    border: 1px solid color-mix(in srgb, var(--section-accent) 35%, ${t.surfaceBorder});
                    background: color-mix(in srgb, var(--section-accent) 8%, transparent);
                    color: var(--section-accent);
                    font-size: 18px; line-height: 1; font-weight: 600;
                    display: flex; align-items: center; justify-content: center;
                    transition: background 0.12s;
                }
                .zone-mini:hover { background: color-mix(in srgb, var(--section-accent) 20%, transparent); }
                .zone-range {
                    -webkit-appearance: none; appearance: none;
                    flex: 1; min-width: 0; height: 6px; border-radius: 3px;
                    cursor: pointer; outline: none;
                    background: linear-gradient(to right,
                        var(--section-accent) 0%, var(--section-accent) var(--fill, 0%),
                        ${e?"rgba(255,255,255,0.14)":"rgba(0,0,0,0.12)"} var(--fill, 0%),
                        ${e?"rgba(255,255,255,0.14)":"rgba(0,0,0,0.12)"} 100%);
                }
                .zone-range::-webkit-slider-thumb {
                    -webkit-appearance: none; width: 16px; height: 16px; border-radius: 50%;
                    background: var(--section-accent); border: 2px solid #fff;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.45); cursor: pointer;
                }
                .zone-range::-moz-range-thumb {
                    width: 16px; height: 16px; border-radius: 50%;
                    background: var(--section-accent); border: 2px solid #fff;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.45); cursor: pointer;
                }

                /* SOC-zone strip */
                .soc-strip { padding: 4px 2px 12px; }
                .soc-bar {
                    position: relative; display: flex;
                    height: 14px; border-radius: 7px; overflow: hidden;
                    margin-bottom: 22px;
                }
                .soc-zone { height: 100%; }
                .soc-now {
                    position: absolute; top: -3px; width: 3px; height: 20px;
                    background: #fff; border-radius: 2px;
                    box-shadow: 0 0 4px rgba(0,0,0,0.6); transform: translateX(-50%);
                }
                .soc-tick {
                    position: absolute; bottom: -20px; transform: translateX(-50%);
                    font-size: 10px; color: var(--secondary-text-color, ${t.textSec});
                }
                .soc-tick::before {
                    content: ''; position: absolute; top: -7px; left: 50%;
                    width: 1px; height: 6px; background: var(--secondary-text-color, ${t.textSec});
                    opacity: 0.5; transform: translateX(-50%);
                }
                .soc-legend {
                    display: flex; flex-wrap: wrap; gap: 4px 14px;
                    font-size: 11px; color: var(--secondary-text-color, ${t.textSec});
                }
                .soc-legend span { display: inline-flex; align-items: center; gap: 5px; }
                .soc-legend i { width: 9px; height: 9px; border-radius: 2px; display: inline-block; }

                /* #528 staged-changes Apply bar (sticky at top of the card) */
                .apply-bar {
                    position: sticky; top: 6px; z-index: 5;
                    display: flex; align-items: center; gap: 10px;
                    margin: 0 0 12px; padding: 9px 12px;
                    border-radius: 10px;
                    background: color-mix(in srgb, ${s} 16%, ${t.surface});
                    border: 1px solid color-mix(in srgb, ${s} 45%, ${t.surfaceBorder});
                    box-shadow: 0 2px 10px rgba(0,0,0,0.25);
                }
                .apply-msg { flex: 1; font-size: 12.5px; font-weight: 600;
                    display: inline-flex; align-items: center; gap: 8px; }
                .apply-btn, .apply-discard {
                    border: none; border-radius: 8px; cursor: pointer;
                    font-size: 12.5px; font-weight: 700; padding: 6px 14px;
                }
                .apply-btn { background: ${s}; color: #fff; }
                .apply-discard {
                    background: transparent; color: var(--secondary-text-color, ${t.textSec});
                    border: 1px solid ${t.surfaceBorder};
                }
                .apply-spin {
                    width: 13px; height: 13px; border-radius: 50%;
                    border: 2px solid color-mix(in srgb, ${s} 30%, transparent);
                    border-top-color: ${s}; display: inline-block;
                    animation: applyspin 0.7s linear infinite;
                }
                @keyframes applyspin { to { transform: rotate(360deg); } }
                .apply-bar.apply-err {
                    background: color-mix(in srgb, #e57373 18%, ${t.surface});
                    border-color: color-mix(in srgb, #e57373 55%, ${t.surfaceBorder});
                }
                .apply-bar.apply-err .apply-msg { color: #e57373; }
                .pending-dot { color: ${s}; font-size: 9px; margin-left: 6px; vertical-align: middle; }

                /* #528 Phase 4 — add/remove charger */
                .add-charger-btn {
                    display: inline-flex; align-items: center; gap: 6px;
                    margin-top: 8px; padding: 8px 16px; border-radius: 9px; cursor: pointer;
                    background: color-mix(in srgb, #5BC8D8 16%, transparent);
                    border: 1px dashed color-mix(in srgb, #5BC8D8 55%, ${t.surfaceBorder});
                    color: #5BC8D8; font-size: 13px; font-weight: 700;
                }
                .add-charger-btn:hover { background: color-mix(in srgb, #5BC8D8 28%, transparent); }
                .add-charger-btn[disabled] { opacity: 0.5; cursor: default; }
                .charger-remove-x {
                    border: none; background: transparent; cursor: pointer;
                    color: var(--secondary-text-color, ${t.textSec}); font-size: 14px;
                    padding: 2px 6px; border-radius: 6px; line-height: 1;
                }
                .charger-remove-x:hover { color: #e57373; background: color-mix(in srgb, #e57373 15%, transparent); }
                .charger-remove-confirm {
                    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
                    margin: 4px 0 8px; padding: 8px 10px; border-radius: 8px;
                    background: color-mix(in srgb, #e57373 14%, ${t.surface});
                    border: 1px solid color-mix(in srgb, #e57373 45%, ${t.surfaceBorder});
                    font-size: 12.5px;
                }
                .charger-remove-confirm span { flex: 1; }
                .charger-remove-go {
                    border: none; border-radius: 7px; cursor: pointer; font-weight: 700;
                    padding: 5px 12px; background: #e57373; color: #fff; font-size: 12px;
                }
                .charger-remove-cancel {
                    border: 1px solid ${t.surfaceBorder}; border-radius: 7px; cursor: pointer;
                    padding: 5px 12px; background: transparent;
                    color: var(--secondary-text-color, ${t.textSec}); font-size: 12px;
                }

                /* #528 first-run completeness guide */
                .setup-progress { margin: 2px 2px 12px; }
                .setup-progress-top {
                    display: flex; justify-content: space-between; align-items: baseline;
                    margin-bottom: 6px;
                }
                .setup-progress-label { font-size: 13px; font-weight: 700; }
                .setup-progress-pct { font-size: 12px; color: var(--secondary-text-color, ${t.textSec}); }
                .setup-progress-bar {
                    height: 7px; border-radius: 4px; overflow: hidden;
                    background: ${e?"rgba(255,255,255,0.12)":"rgba(0,0,0,0.1)"};
                }
                .setup-progress-fill {
                    height: 100%; border-radius: 4px;
                    background: #ffb74d; transition: width 0.4s cubic-bezier(0.4,0,0.2,1);
                }
                .setup-progress-fill.done { background: #81c784; }
                .chip-todo { cursor: pointer; border-style: dashed !important; }
                .chip-todo:hover { border-color: ${s} !important; }
                .chip-todo .c-warn { color: ${s} !important; font-weight: 700; white-space: nowrap; }

                /* (#1021) the grid operator's relay block */
                .operator-relay {
                    margin-top: 10px; padding-top: 8px;
                    border-top: 1px solid ${t.surfaceBorder};
                }
                .operator-relay-head {
                    font-size: 12px; font-weight: 600; letter-spacing: .04em;
                    text-transform: uppercase; opacity: .7; margin: 2px 0 6px;
                }
                .setting-help-text {
                    font-size: 11px; line-height: 1.35;
                    color: var(--secondary-text-color, ${t.textSec});
                    opacity: 0.75; padding: 2px 4px 6px 0; margin-top: -4px;
                    font-style: italic;
                }

                /* Entity picker + slider cells for option-only fields */
                .picker-cell { display: flex; flex-direction: column; padding: 6px 0; }
                .picker-row { display: flex; align-items: center; gap: 10px; }
                .picker-label {
                    font-size: 14px; font-weight: 500;
                    min-width: 150px; flex-shrink: 0;
                }
                .src-chip { display: inline-flex; align-items: center; margin-left: 8px; padding: 1px 8px;
                    border-radius: 10px; font-size: 11px; font-weight: 500; vertical-align: middle; }
                .src-chip.detected { background: rgba(141,200,146,.18); color: #5f9e65; }
                .src-chip.you { background: rgba(72,143,194,.18); color: #488fc2; }
                .src-chip.none { background: rgba(160,160,160,.15); color: #9e9e9e; }
                .src-sub { display: block; font-size: 11px; opacity: .75; margin-top: 2px; font-weight: 400; }
                .src-use { color: #488fc2; cursor: pointer; text-decoration: underline; margin-left: 6px; }
                .src-legend { font-size: 12px; opacity: .85; margin: 4px 0 10px; }
                .picker-row ha-entity-picker { flex: 1; min-width: 0; }
                .save-status {
                    font-size: 11px; padding: 2px 0 0 154px;
                    color: var(--secondary-text-color, ${t.textSec});
                }
                .save-status.ok { color: #8DC892; }
                .save-status.err { color: var(--error-color, #d33); }

                .setup-intro {
                    font-size: 12px; line-height: 1.45;
                    color: var(--secondary-text-color, ${t.textSec});
                    padding: 6px 0 12px; border-bottom: 1px solid ${t.surfaceBorder};
                    margin-bottom: 8px;
                }
                .hp-status, .hp-form { display: flex; flex-direction: column; }
                .hp-status { margin-bottom: 6px; padding-bottom: 6px; border-bottom: 1px solid ${t.surfaceBorder}; }

                /* number input for box-mode large-range fields */
                .num-input-wrap { display: flex; align-items: center; gap: 6px; }
                .sem-num-input {
                    background: ${t.surface};
                    border: 1px solid ${t.surfaceBorder};
                    border-radius: 8px;
                    color: var(--primary-text-color, ${t.text});
                    padding: 5px 8px; font-size: 14px; font-family: inherit;
                    width: 90px; text-align: right;
                    font-variant-numeric: tabular-nums;
                    outline: none;
                }
                .sem-num-input:focus { border-color: ${s}; }
                .stepper-cell.is-disabled .ctrl-row { opacity: 0.5; }
                .sem-num-input:disabled { cursor: not-allowed; }
                .num-unit {
                    font-size: 12px; color: var(--secondary-text-color, ${t.textSec});
                }

                @media (max-width: 500px) {
                    .picker-row { flex-wrap: wrap; }
                    .picker-label { flex: 1 1 100%; min-width: 0; }
                    .picker-row ha-entity-picker { flex: 1 1 100%; }
                    .save-status { padding-left: 0; }
                }

                .charger-block {
                    border-left: 3px solid ${s};
                    padding: 6px 0 6px 10px; margin-bottom: 10px;
                }
                .charger-block-title {
                    display: flex; align-items: center; gap: 6px;
                    font-size: 14px; font-weight: 600;
                    margin-bottom: 6px;
                }

                .ha-settings-btn {
                    display: inline-flex; align-items: center; gap: 4px;
                    padding: 6px 12px; border-radius: 8px;
                    background: ${t.surface}; border: 1px solid ${t.surfaceBorder};
                    color: var(--primary-text-color, ${t.text});
                    font-size: 13px; cursor: pointer;
                    transition: background 0.15s, border-color 0.15s;
                }
                .ha-settings-btn:hover { background: ${t.surfaceHover}; border-color: ${s}; }

                /* (#915) accept a proposed role — the same affordance,
                   smaller, because it sits inside a row rather than under a
                   section heading. */
                .sem-btn {
                    display: inline-flex; align-items: center; gap: 4px;
                    padding: 3px 10px; border-radius: 7px;
                    background: ${t.surface}; border: 1px solid ${t.surfaceBorder};
                    color: var(--primary-text-color, ${t.text});
                    font-size: 12px; cursor: pointer;
                    transition: background 0.15s, border-color 0.15s;
                }
                .sem-btn:hover:not([disabled]) { background: ${t.surfaceHover}; border-color: ${s}; }
                .sem-btn[disabled] { opacity: 0.55; cursor: default; }

                /* ── #605 staged-changes UI ── */
                .zone-knob.dirty, .stepper-cell.dirty {
                    border-left: 3px solid var(--section-accent, ${s});
                    padding-left: 8px; margin-left: -11px;
                    border-radius: 4px;
                }
                .dirty-dot {
                    color: var(--section-accent, ${s});
                    font-size: 10px; margin: 0 4px; vertical-align: middle;
                }
                .section-stage-bar {
                    display: flex; align-items: center; gap: 10px;
                    margin-top: 12px; padding: 8px 12px;
                    background: ${t.surface}; border: 1px solid var(--section-accent, ${s});
                    border-radius: 10px;
                    position: sticky; bottom: 8px; z-index: 3;
                    backdrop-filter: blur(8px);
                }
                .stage-count { font-size: 12.5px; color: var(--section-accent, ${s}); font-weight: 600; flex: 1; }
                .stage-err { font-size: 12px; color: #ef5350; }
                .stage-btn {
                    padding: 6px 14px; border-radius: 8px; font-size: 13px;
                    cursor: pointer; border: 1px solid ${t.surfaceBorder};
                    background: ${t.surface}; color: var(--primary-text-color, ${t.text});
                    transition: background 0.15s, border-color 0.15s;
                }
                .stage-btn.apply {
                    background: var(--section-accent, ${s}); color: #fff;
                    border-color: transparent; font-weight: 600;
                }
                .stage-btn:disabled { opacity: 0.55; cursor: default; }
                .stage-btn:not(:disabled):hover { filter: brightness(1.12); }
                .header-dirty-badge {
                    font-size: 11px; font-weight: 700;
                    color: var(--section-accent, ${s});
                    margin-left: 6px; white-space: nowrap;
                }

                /* ── #606 per-row help + defaults + docs ── */
                .row-help-btn {
                    color: ${t.textDim||"rgba(150,160,175,0.8)"};
                    cursor: pointer; margin-left: 5px; vertical-align: middle;
                    opacity: 0.7; transition: opacity 0.15s, color 0.15s;
                }
                .row-help-btn:hover { opacity: 1; }
                .row-help-btn.on { color: var(--section-accent, ${s}); opacity: 1; }
                .help-default {
                    display: inline-block; margin-left: 8px;
                    font-size: 11px; font-weight: 600;
                    color: var(--section-accent, ${s});
                    opacity: 0.9; white-space: nowrap;
                }
                .section-docs-link {
                    display: inline-flex; align-items: center;
                    color: ${t.textDim||"rgba(150,160,175,0.8)"};
                    margin-left: 6px; opacity: 0.7; transition: opacity 0.15s;
                }
                .section-docs-link:hover { opacity: 1; color: var(--section-accent, ${s}); }
                .help-reset-btn {
                    display: inline-block; margin-left: 8px;
                    padding: 1px 8px; border-radius: 9px;
                    font-size: 11px; cursor: pointer;
                    border: 1px solid ${t.surfaceBorder};
                    background: transparent;
                    color: var(--section-accent, ${s});
                }
                .help-reset-btn:hover { border-color: var(--section-accent, ${s}); }
            </style>
            <ha-card>
                <div class="wrap">
                    ${""}
                    <div class="card-help-bar">
                        ${""}
                        <div class="view-switch" role="group">
                            <button class="view-opt ${this._advanced?"":"on"}"
                                    aria-pressed=${this._advanced?"false":"true"}
                                    @click=${()=>this._setView(!1)}>${this._t("config_view_everyday")}</button>
                            <button class="view-opt ${this._advanced?"on":""}"
                                    aria-pressed=${this._advanced?"true":"false"}
                                    @click=${()=>this._setView(!0)}>${this._t("config_advanced_label")}</button>
                        </div>
                        <span class="help-toggle-labeled ${this._showHelp?"on":""}"
                              @click=${()=>this._toggleHelp()}>
                            <ha-icon
                                icon="${this._showHelp?"mdi:help-circle":"mdi:help-circle-outline"}"
                                style="--mdc-icon-size:16px"
                            ></ha-icon>
                            <span>${this._t("config_help_label")}</span>
                        </span>
                    </div>
                    ${this._renderApplyBar()}
                    ${this._renderGroups(i,t)}
                </div>
            </ha-card>
        `}getCardSize(){return 12}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"sem-config-card",name:"SEM Configuration Card",description:"In-dashboard SEM configuration surface (replaces the Settings → SEM → Configure flow for most users)",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-config-card",preview:!1});const ra="sem-config-tab-introduced-v1";kt("sem-onboarding-banner",class extends Lt{static get watchedEntities(){return[]}static get properties(){return{...super.properties,_dismissed:{state:!0}}}constructor(){super(),this._dismissed=this._isDismissed()}setConfig(t){super.setConfig(t),this._configPath=t.config_tab_path||"/config"}_isDismissed(){try{return"1"===localStorage.getItem(ra)}catch(t){return!1}}_dismiss(){try{localStorage.setItem(ra,"1")}catch(t){}this._dismissed=!0}_openConfig(){const t=window.location.pathname.split("/").filter(Boolean);if(t.length>=2){const e="/"+t.slice(0,-1).join("/");window.history.pushState(null,"",`${e}/config`)}else window.history.pushState(null,"",this._configPath);window.dispatchEvent(new Event("location-changed",{composed:!0})),this._dismiss()}render(){if(this._dismissed)return K;if(!this._config)return K;const t=this._theme(),e="#8DC892";return H`
            <style>
                :host { display: block; }
                .banner {
                    display: flex; align-items: center; gap: 12px;
                    padding: 14px 16px; border-radius: 14px; margin-bottom: 12px;
                    background:
                        linear-gradient(135deg, ${e}22 0%, ${e}0B 100%),
                        ${t.surface};
                    border: 1px solid ${e}55;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
                    color: var(--primary-text-color, ${t.text});
                    font-family: 'Segoe UI','Roboto',sans-serif;
                }
                .icon {
                    --mdc-icon-size: 28px;
                    color: ${e};
                    flex-shrink: 0;
                }
                .text { flex: 1; min-width: 0; }
                .title {
                    font-size: 14px; font-weight: 700; letter-spacing: 0.2px;
                    margin-bottom: 2px;
                }
                .body {
                    font-size: 12px; line-height: 1.4;
                    color: var(--secondary-text-color, ${t.textSec});
                }
                .actions { display: flex; gap: 6px; flex-shrink: 0; }
                button {
                    padding: 7px 14px; border-radius: 9px;
                    font-size: 12px; font-weight: 600; font-family: inherit;
                    cursor: pointer; border: 1px solid transparent;
                    transition: background 0.15s, border-color 0.15s, transform 0.05s;
                }
                button:active { transform: scale(0.97); }
                .open {
                    background: ${e}; color: #1a1d24;
                }
                .open:hover { background: color-mix(in srgb, ${e} 88%, white); }
                .dismiss {
                    background: transparent; color: var(--secondary-text-color, ${t.textSec});
                    border-color: ${t.surfaceBorder};
                }
                .dismiss:hover { background: ${t.surfaceHover}; }
                @media (max-width: 500px) {
                    .banner { flex-wrap: wrap; }
                    .text { flex: 1 1 100%; order: 1; }
                    .icon { order: 0; }
                    .actions { flex: 1 1 100%; order: 2; justify-content: flex-end; }
                }
            </style>
            <div class="banner">
                <ha-icon class="icon" icon="mdi:cog-sync-outline"></ha-icon>
                <div class="text">
                    <div class="title">${this._t("onboarding_banner_title")}</div>
                    <div class="body">${this._t("onboarding_banner_body")}</div>
                </div>
                <div class="actions">
                    <button class="open" @click=${()=>this._openConfig()}>
                        ${this._t("onboarding_banner_open")}
                    </button>
                    <button class="dismiss" @click=${()=>this._dismiss()}>
                        ${this._t("onboarding_banner_dismiss")}
                    </button>
                </div>
            </div>
        `}getCardSize(){return 1}static getStubConfig(){return{}}},{type:"sem-onboarding-banner",name:"SEM Onboarding Banner",description:"One-time welcome banner pointing existing users to the new Configuration tab",documentationURL:"https://github.com/traktore-org/sem-community/blob/develop/docs/DASHBOARD_GUIDE.md#sem-onboarding-banner",preview:!1});class aa extends Lt{static get properties(){return{...super.properties,section:{type:String},label:{type:String},_open:{state:!0},_busy:{state:!0},_payload:{state:!0},_error:{state:!0},_copied:{state:!0}}}constructor(){super(),this.section="all",this.label="",this._open=!1,this._busy=!1,this._payload=null,this._error=null,this._copied=!1,this._copiedTimer=null}disconnectedCallback(){super.disconnectedCallback(),this._copiedTimer&&(clearTimeout(this._copiedTimer),this._copiedTimer=null,this._copied=!1)}static get watchedEntities(){return[]}async _click(){if(this._hass){this._open=!0,this._busy=!0,this._error=null,this._payload=null;try{const t=await this._hass.callService("solar_energy_management","diagnose",{section:this.section||"all"},void 0,void 0,!0);this._payload=t?.response||t}catch(t){this._error=t?.message||String(t),console.error("[sem-diagnose-button] failed",t)}finally{this._busy=!1}}}_close(){this._open=!1,this._copied=!1,this._payload=null,this._error=null}async _copy(){if(!this._payload)return;const t=JSON.stringify(this._payload,null,2),e=()=>{this._copied=!0,this._error=null,this._copiedTimer&&clearTimeout(this._copiedTimer),this._copiedTimer=setTimeout(()=>{this._copiedTimer=null,this._copied=!1},1500)};if(navigator?.clipboard?.writeText&&!1!==window.isSecureContext)try{return await navigator.clipboard.writeText(t),void e()}catch(t){console.warn("[sem-diagnose-button] modern clipboard refused, falling back to execCommand",t)}try{const s=document.createElement("textarea");s.value=t,s.setAttribute("readonly",""),s.style.position="fixed",s.style.top="0",s.style.left="0",s.style.width="1px",s.style.height="1px",s.style.opacity="0",document.body.appendChild(s),s.focus(),s.select();const i=document.execCommand("copy");if(document.body.removeChild(s),i)return void e();console.error('[sem-diagnose-button] execCommand("copy") returned false')}catch(t){console.error("[sem-diagnose-button] legacy clipboard fallback threw",t)}this._error=this._t("config_diagnose_clipboard_failed")}render(){const t=this._theme(),e=t.accent||"#5BC8D8",s=this.label||this._t("config_diagnose");return H`
            <style>
                :host { display: inline-flex; }
                .btn {
                    display: inline-flex; align-items: center; gap: 4px;
                    padding: 5px 10px; border-radius: 8px; cursor: pointer;
                    background: ${t.surface}; color: var(--primary-text-color, ${t.text});
                    border: 1px solid ${t.surfaceBorder};
                    font-size: 12px; font-family: inherit;
                    transition: background 0.15s, border-color 0.15s;
                }
                .btn:hover { background: ${t.surfaceHover}; border-color: ${e}; }
                .modal-backdrop {
                    position: fixed; inset: 0;
                    background: rgba(0,0,0,0.72);
                    backdrop-filter: blur(6px);
                    -webkit-backdrop-filter: blur(6px);
                    display: flex; align-items: center; justify-content: center;
                    z-index: 9999; padding: 20px;
                }
                .modal {
                    background: var(--ha-card-background, var(--card-background-color, #1a1d24));
                    border: 1px solid ${t.surfaceBorder};
                    border-radius: 14px; padding: 18px;
                    max-width: 800px; width: 100%;
                    max-height: 80vh; overflow: hidden;
                    display: flex; flex-direction: column;
                    box-shadow: 0 12px 40px rgba(0,0,0,0.65);
                    color: var(--primary-text-color, ${t.text});
                    font-family: 'Segoe UI','Roboto',sans-serif;
                }
                .modal-header {
                    display: flex; align-items: center; gap: 10px;
                    padding-bottom: 12px;
                    border-bottom: 1px solid ${t.surfaceBorder};
                }
                .modal-title { font-size: 16px; font-weight: 700; flex: 1; }
                .icon-btn {
                    background: transparent; border: none;
                    color: var(--secondary-text-color, ${t.textSec});
                    cursor: pointer; padding: 4px; border-radius: 50%;
                    transition: background 0.15s;
                }
                .icon-btn:hover { background: ${t.surfaceHover}; }
                .modal-body {
                    flex: 1; overflow: auto; padding: 12px 0;
                    font-family: ui-monospace, 'SF Mono', 'Roboto Mono', monospace;
                    font-size: 11px; line-height: 1.5;
                    white-space: pre-wrap; word-break: break-word;
                    color: var(--primary-text-color, ${t.text});
                }
                .modal-footer {
                    display: flex; gap: 8px; padding-top: 12px;
                    border-top: 1px solid ${t.surfaceBorder};
                    justify-content: flex-end;
                }
                .footer-btn {
                    padding: 7px 14px; border-radius: 9px;
                    font-size: 12px; font-weight: 600; font-family: inherit;
                    cursor: pointer; border: 1px solid transparent;
                }
                .footer-btn.primary {
                    background: ${e}; color: #1a1d24;
                    border-color: ${e};
                }
                .footer-btn.primary:hover {
                    background: color-mix(in srgb, ${e} 88%, white);
                }
                .footer-btn.secondary {
                    background: transparent;
                    color: var(--secondary-text-color, ${t.textSec});
                    border-color: ${t.surfaceBorder};
                }
                .footer-btn.secondary:hover { background: ${t.surfaceHover}; }
                .footer-btn.copied {
                    background: #8DC892; color: #1a1d24;
                    border-color: #8DC892;
                }
                .busy {
                    text-align: center; padding: 30px;
                    color: var(--secondary-text-color, ${t.textSec});
                }
                .error {
                    color: var(--error-color, #d33);
                    padding: 12px;
                    background: rgba(220, 50, 50, 0.1);
                    border-radius: 8px;
                    font-family: ui-monospace, monospace;
                    font-size: 11px;
                }
            </style>
            <button class="btn" @click=${this._click}>
                <ha-icon icon="mdi:stethoscope" style="--mdc-icon-size:14px"></ha-icon>
                ${s}
            </button>
            ${this._open?H`
                <div class="modal-backdrop" @click=${t=>t.target.classList.contains("modal-backdrop")&&this._close()}>
                    <div class="modal">
                        <div class="modal-header">
                            <ha-icon icon="mdi:stethoscope" style="--mdc-icon-size:18px;color:${e}"></ha-icon>
                            <span class="modal-title">${this._t("config_diagnose")} — ${this.section}</span>
                            <button class="icon-btn" @click=${this._close} title="${this._t("cancel")||"Close"}">
                                <ha-icon icon="mdi:close" style="--mdc-icon-size:18px"></ha-icon>
                            </button>
                        </div>
                        <div class="modal-body">
                            ${this._busy?H`<div class="busy">${this._t("config_diagnose_busy")||"Collecting diagnostics…"}</div>`:K}
                            ${this._error?H`<div class="error">${this._error}</div>`:K}
                            ${this._busy||this._error||!this._payload?K:H`${JSON.stringify(this._payload,null,2)}`}
                        </div>
                        <div class="modal-footer">
                            <button class="footer-btn secondary" @click=${this._close}>
                                ${this._t("cancel")||"Close"}
                            </button>
                            ${this._payload?H`
                                <button class="footer-btn ${this._copied?"copied":"primary"}" @click=${this._copy}>
                                    ${this._copied?this._t("copied"):this._t("config_diagnose_copy")||"Copy to clipboard"}
                                </button>
                            `:K}
                        </div>
                    </div>
                </div>
            `:K}
        `}}customElements.get("sem-diagnose-button")||customElements.define("sem-diagnose-button",aa),console.info("%c SEM Cards %c Lit Bundle ","color: #4db6ac; font-weight: bold; background: #1e232d; padding: 2px 6px; border-radius: 4px 0 0 4px;","color: #ff9800; background: #1e232d; padding: 2px 6px; border-radius: 0 4px 4px 0;");
