"""临时验证脚本：检查 docker-compose.yml 结构。"""
import yaml

with open(r'E:\langChain_langGraph\docker-compose.yml', encoding='utf-8') as f:
    d = yaml.safe_load(f)

print('name:', d.get('name'))
print('services:', list(d['services'].keys()))
print('volumes:', list(d.get('volumes', {}).keys()))
print('networks:', list(d.get('networks', {}).keys()))
for name, svc in d['services'].items():
    print()
    print(f'### {name}')
    if 'image' in svc:
        print('  image:', svc['image'])
    if 'build' in svc:
        print('  build:', svc['build'])
    if 'ports' in svc:
        print('  ports:', svc['ports'])
    if 'profiles' in svc:
        print('  profiles:', svc['profiles'])
    if 'volumes' in svc:
        print('  volumes:', len(svc['volumes']), 'mounts')
    if 'depends_on' in svc:
        print('  depends_on:', svc['depends_on'])
    if 'healthcheck' in svc:
        print('  healthcheck: enabled')
