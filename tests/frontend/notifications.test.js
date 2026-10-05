const {pushBlocker,deviceLabel,base64UrlBytes}=require('../../frontend/notifications');

test('explains exactly why notifications cannot be turned on',()=>{
 const ok={secure:true,ios:false,standalone:false,pushManager:true,origin:'https://cli.example.com'};
 expect(pushBlocker(ok)).toBeNull();
 expect(pushBlocker({...ok,secure:false,origin:'http://100.64.0.1:8790'})).toEqual(['Уведомлениям нужен HTTPS-адрес панели. Сейчас она открыта по {0}.',['http://100.64.0.1:8790']]);
 expect(pushBlocker({...ok,ios:true})[0]).toContain('«Домой»');
 expect(pushBlocker({...ok,ios:true,standalone:true})).toBeNull();
 expect(pushBlocker({...ok,pushManager:false})[0]).toContain('не поддерживает');
});

test('names devices so the list in settings is recognisable',()=>{
 expect(deviceLabel('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1')).toBe('iPhone · Safari');
 expect(deviceLabel('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130.0 Safari/537.36')).toBe('Mac · Chrome');
 expect(deviceLabel('Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/130.0 Safari/537.36 Edg/130.0')).toBe('Windows · Edge');
 expect(deviceLabel('curl/8')).toBe('Browser');
});

test('decodes the VAPID public key from base64url',()=>{
 expect([...base64UrlBytes('BP4z-_8')]).toEqual([0x04,0xfe,0x33,0xfb,0xff]);
});
