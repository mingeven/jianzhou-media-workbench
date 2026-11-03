(() => {
  const field = (name, label, type = 'text', extra = {}) => ({ name, label, type, ...extra });
  const select = (name, label, options) => field(name, label, 'select', { options });
  const required = { required: true };
  const platforms = [['douyin','抖音'], ['xhs','小红书'], ['channels','视频号'], ['bilibili','哔哩哔哩'], ['kuaishou','快手'], ['tiktok','TikTok']];
  const freq = select('sync_frequency', '同步频率', [['每 6 小时','每 6 小时'], ['每日','每日'], ['手动','手动']]);
  const settingsGroups = {
    providers: [
      { key:'llm', label:'语言模型', secret:['api_key','模型 API 密钥'], fields:[
        field('api_base','API 地址','url',required), field('fast_model','快速模型'), field('analysis_model','分析模型'),
        field('writing_model','写作模型'), field('structured_model','结构化模型')
      ] },
      { key:'source', label:'TikHub 数据源', secret:['tikhub_api_key','TikHub API 密钥'], fields:[
        field('daily_request_limit','每日请求上限','number',{ ...required, min:1, max:100000 })
      ] },
      { key:'voice', label:'语音转写', secret:['api_key','转写 API 密钥'], fields:[
        field('api_base','API 地址','url'), field('asr_model','转写模型')
      ] },
      { key:'image', label:'图像模型', secret:['api_key','图像 API 密钥'], fields:[
        field('api_base','API 地址','url'), field('model','生成模型')
      ] }
    ],
    system: [
      { key:'cost', label:'用量预算', fields:[
        field('daily_budget','日预算（元）','number',{ ...required, min:0, step:.01 }),
        field('monthly_budget','月预算（元）','number',{ ...required, min:0, step:.01 }),
        field('weekly_capacity_hours','每周内容产能（小时）','number',{ ...required, min:0, max:168, step:.5 })
      ] }
    ]
  };
  const title = field('name','名称','text',{ ...required, minlength:2, maxlength:80 });
  const prompt = (key,label,maxlength) => field(key,label,'textarea',{ ...required, minlength:20, maxlength });
  const planDate = field('scheduled_date','排期','date');
  const recordGroups = {
    library: [
      { key:'templates', label:'视觉内容模板', singular:'模板', url:'/api/visuals/templates', update:'put', remove:true, removeLabel:'归档', makeDefault:true,
        title:r=>r.name, summary:r=>[r.ratio,r.is_default?'默认':'',r.builtin?'内置':'自定义'].filter(Boolean).join(' · '),
        fields:[title,select('ratio','尺寸',[['3:4','3:4'],['1:1','1:1'],['16:9','16:9'],['9:16','9:16']]),select('template_type','类型',[['cover','封面'],['graphic','图文']]),prompt('prompt_template','模板内容',12000)],
        defaults:{ratio:'3:4',template_type:'cover'}, extra:r=>({template:r?.template || {}}) },
      { key:'prompts', label:'提示词预设', singular:'提示词', url:'/api/visuals/prompt-presets', update:'put', remove:true, removeLabel:'归档',
        title:r=>r.name, summary:r=>r.scope === 'cover' ? '封面' : '图文',
        fields:[title,select('scope','用途',[['cover','封面'],['graphic_note','图文']]),prompt('template_text','提示词正文',16000),field('negative_prompt','排除内容','textarea',{maxlength:4000})],
        defaults:{scope:'cover'} }
    ],
    accounts: [
      { key:'owned', label:'平台账号', singular:'平台账号', url:'/api/accounts', update:'patch', remove:true,
        title:r=>r.display_name, summary:r=>[r.platform_label,r.sync_frequency].join(' · '), editFields:[freq],
        fields:[select('platform','平台',platforms),field('link','账号主页或 ID','text',{...required,maxlength:2048}),field('display_name','显示名称','text',{maxlength:200}),freq],
        defaults:{platform:'douyin',sync_frequency:'每 6 小时'}, extra:r=>r ? {} : {source_mode:'manual'} },
      { key:'benchmarks', label:'对标账号', singular:'对标账号', url:'/api/benchmarks', update:'put', updateSuffix:'/monitor', remove:true,
        title:r=>r.name || r.nickname || r.link || r.id, summary:r=>[r.platform_label,'已缓存 '+r.works_count+' 条'].join(' · '),
        fields:[field('link','账号主页或分享链接','text',{...required,maxlength:2048}),select('platform','平台',[['','自动识别'],...platforms]),field('scan_count','初次扫描数量','number',{...required,min:1,max:500}),field('note','备注','text',{maxlength:300})],
        editFields:[field('enabled','开启监控','checkbox'),field('frequency_hours','监控间隔（小时）','number',{...required,min:1,max:168})],
        editDefaults:r=>({enabled:Boolean(r.monitor_enabled ?? true),frequency_hours:r.monitor_frequency_hours || 24}),
        defaults:{scan_count:10,platform:''}, queued:true }
    ],
    tasks: [
      { key:'tasks', label:'内容任务与排期', singular:'任务', url:'/api/planning/tasks', list:'/api/planning/board', update:'patch',
        rows:r=>[...r.columns.flatMap(c=>c.cards),...(r.done || [])],
        title:r=>r.title, summary:r=>[r.scheduled_date || '未排期', r.platform, r.status].filter(Boolean).join(' · '),
        fields:[field('title','任务标题','text',{...required,maxlength:200}),field('platform','平台'),planDate,field('estimate_h','预计耗时（小时）','number',{...required,min:0,max:168,step:.25})],
        editFields:[{...planDate,required:true}], defaults:{estimate_h:1.5} }
    ]
  };
  let fieldSet = 0;
  const app = Vue.createApp({
    template: document.getElementById('admin-template').innerHTML,
    data: () => ({
      authenticated:false, configured:false, loading:true, busy:false, error:'', notice:'', password:'',
      view:'providers', data:null, secrets:{}, editor:null, loadId:0, settingsGroups, recordGroups,
      tabs:[
        {id:'providers',label:'模型与数据源',description:'配置工作台使用的模型、数据源和凭据。'},
        {id:'library',label:'模板与提示词',description:'管理视觉内容模板及写作时可复用的视觉提示词。'},
        {id:'accounts',label:'平台与对标账号',description:'维护自有账号和对标账号的监控设置。'},
        {id:'tasks',label:'任务与排期',description:'新增内容任务，并调整计划日期。'},
        {id:'operations',label:'运行与用量',description:'查看运行状态、最近用量、错误和管理操作。'},
        {id:'system',label:'系统与备份',description:'管理用量预算、每周产能和数据库快照。'}
      ],
      logTables:[
        {key:'audit',label:'管理操作记录',columns:[['occurred_at','时间'],['method','操作'],['route','接口'],['status','结果']]},
        {key:'errors',label:'最近错误',columns:[['ts','时间'],['code','错误'],['stage','阶段'],['trace_id','追踪编号']]},
        {key:'ledger',label:'用量明细',columns:[['ts','时间'],['provider','服务'],['model','模型'],['cost','金额']]}
      ]
    }),
    computed:{ active() { return this.tabs.find(t=>t.id === this.view); } },
    mounted() { this.checkSession(); },
    methods:{
      showError(error) {
        if (error?.code === 'ADMIN_REQUIRED') {
          this.authenticated = false; this.data = null; this.editor = null; this.secrets = {};
        }
        this.error = error?.message || '操作未完成，请重试。';
      },
      async checkSession() {
        this.loading = true; this.error = '';
        try {
          const session = await api.get('/api/admin/session');
          this.configured = session.configured; this.authenticated = session.authenticated;
          if (this.authenticated) return await this.refresh();
        } catch (e) { this.showError(e); }
        finally { this.loading = false; }
      },
      async signIn() {
        this.busy = true; this.error = '';
        try {
          await api.post('/api/admin/login',{password:this.password});
          if (new URLSearchParams(location.search).get('next') === 'workbench') {
            location.assign('/'); return;
          }
          this.authenticated = true;
          await this.refresh();
        } catch (e) { this.showError(e); }
        finally { this.password = ''; this.busy = false; }
      },
      async signOut() {
        await this.action(async () => {
          await api.post('/api/admin/logout');
          this.loadId++; this.authenticated = false; this.loading = false;
          this.data = null; this.secrets = {}; this.editor = null; this.notice = '';
        });
      },
      choose(id) {
        this.view = id; this.notice = ''; this.data = null; this.editor = null; this.secrets = {};
        this.refresh();
      },
      async refresh() {
        const id = ++this.loadId, view = this.view;
        this.loading = true; this.error = '';
        try {
          let data;
          if (settingsGroups[view]) data = await api.get('/api/settings');
          else if (view === 'operations') {
            const [runtime,usage,ledger,operations] = await Promise.all(['/api/settings/runtime','/api/usage/summary','/api/usage/ledger','/api/admin/operations'].map(url=>api.get(url)));
            data = {runtime,usage,ledger,operations};
          } else {
            data = Object.fromEntries(await Promise.all(recordGroups[view].map(async group=>{
              const rows = await api.get(group.list || group.url);
              return [group.key, group.rows ? group.rows(rows) : rows];
            })));
          }
          if (id === this.loadId) this.data = data;
        } catch (e) { if (id === this.loadId) this.showError(e); }
        finally { if (id === this.loadId) this.loading = false; }
      },
      async action(fn) {
        if (this.busy) return;
        this.busy = true; this.error = ''; this.notice = '';
        try { await fn(); } catch (e) { this.showError(e); }
        finally { this.busy = false; }
      },
      async saveSettings(group) {
        await this.action(async () => {
          const values = Object.fromEntries(group.fields.map(({name})=>[name,this.data[group.key][name]]));
          if (group.secret && this.secrets[group.key]?.trim()) values[group.secret[0]] = this.secrets[group.key].trim();
          this.secrets[group.key] = '';
          await api.put('/api/settings',{section:group.key,values});
          this.notice = group.label + '已保存。'; await this.refresh();
        });
      },
      edit(group,row) {
        this.error = ''; this.notice = '';
        const fields = row && group.editFields || group.fields;
        const source = row ? {...row,...group.editDefaults?.(row)} : (group.defaults || {});
        const values = Object.fromEntries(fields.map(({name})=>[name,source[name] ?? '']));
        this.editor = {group:group.key,id:row?.id,fields,values,row};
      },
      async saveRecord(group) {
        await this.action(async () => {
          const {id,row,values} = this.editor;
          const payload = {...values,...group.extra?.(row)};
          if (id) await api[group.update](group.url+'/'+encodeURIComponent(id)+(group.updateSuffix || ''),payload);
          else await api.post(group.url,payload);
          this.notice = !id && group.queued ? '已加入同步队列。处理结果可在工作台的对标账号页查看。' : group.singular + '已保存。';
          this.editor = null; await this.refresh();
        });
      },
      async makeDefault(group,row) {
        await this.action(async () => {
          await api.post(group.url+'/'+encodeURIComponent(row.id)+'/default');
          this.notice = '默认模板已更新。'; await this.refresh();
        });
      },
      async removeRecord(group,row) {
        if (!confirm('确定'+(group.removeLabel || '移除')+'「'+group.title(row)+'」？')) return;
        await this.action(async () => {
          await api.delete(group.url+'/'+encodeURIComponent(row.id));
          this.notice = '操作已保存。'; this.editor = null; await this.refresh();
        });
      },
      logRows(key) { return this.data?.operations?.[key] || this.data?.[key] || []; },
      async backup() {
        await this.action(async () => {
          const resp = await fetch('/api/admin/backup',{method:'POST'});
          if (!resp.ok) throw (await resp.json()).error;
          const url = URL.createObjectURL(await resp.blob()), link = document.createElement('a');
          link.href = url; link.download = 'jianzhou-backup.db'; link.click();
          setTimeout(()=>URL.revokeObjectURL(url),1000);
          this.notice = '数据库快照已生成。';
        });
      }
    }
  });
  app.component('admin-fields',{
    props:['fields','model'], data:()=>({id:'admin-field-'+(++fieldSet)+'-'}),
    template:`<div v-for="f in fields" :key="f.name" class="adm-field">
      <label :for="id+f.name">{{ f.label }}</label>
      <select v-if="f.type==='select'" :id="id+f.name" v-model="model[f.name]"><option v-for="[value,label] in f.options" :key="value" :value="value">{{ label }}</option></select>
      <textarea v-else-if="f.type==='textarea'" :id="id+f.name" v-model.trim="model[f.name]" :required="f.required" :minlength="f.minlength" :maxlength="f.maxlength" rows="4"></textarea>
      <input v-else-if="f.type==='number'" :id="id+f.name" type="number" v-model.number="model[f.name]" :required="f.required" :min="f.min" :max="f.max" :step="f.step || 1">
      <input v-else-if="f.type==='checkbox'" :id="id+f.name" type="checkbox" v-model="model[f.name]">
      <input v-else :id="id+f.name" :type="f.type" v-model.trim="model[f.name]" :required="f.required" :minlength="f.minlength" :maxlength="f.maxlength">
    </div>`
  });
  app.mount('#admin-root');
})();
