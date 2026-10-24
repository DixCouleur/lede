#!/usr/bin/ruby
# Live DNS changes preserve the running AdGuard Home DHCP service.
require 'json'
require 'yaml'

state = ENV.fetch('AX6000_AGH_STATE', '/etc/adguardhome/openclash-upstream.json')
endpoint = ENV.fetch('AX6000_AGH_URL') do
  port = IO.popen(['uci', '-q', 'get', 'AdGuardHome.AdGuardHome.httpport'], &:read).strip
  port = '3000' unless port.match?(/\A[0-9]+\z/)
  "http://127.0.0.1:#{port}"
end
lock = ENV.fetch('AX6000_AGH_LOCK', '/tmp/openclash-adguardhome.lock')
netrc = '/etc/adguardhome/openclash.netrc'
mosdns_mode = ENV.key?('AX6000_MOSDNS_MODE') ? ENV['AX6000_MOSDNS_MODE'] == '1' :
  File.executable?('/sbin/uci') && IO.popen(['uci', '-q', 'get', 'mosdns.config.ax6000_split'], &:read).strip == '1'

def api(endpoint, path, data, netrc)
  args = ['curl', '--fail', '--silent', '--show-error', '--retry', '3', '--retry-connrefused', '--retry-delay', '1', '--noproxy', '*', '--connect-timeout', '2', '--max-time', '8']
  args += ['--netrc-file', netrc] if File.file?(netrc)
  if data == :empty_post
    args += ['--request', 'POST']
  elsif data
    args += ['-H', 'Content-Type: application/json', '--data-binary', JSON.generate(data)]
  end
  result = IO.popen(args + [endpoint + '/control/' + path], &:read)
  raise 'AdGuard Home API request failed' unless $?.success?
  return nil if data || result.empty?
  JSON.parse(result)
end

File.open(lock, File::RDWR | File::CREAT, 0600) do |mutex|
  mutex.flock(File::LOCK_EX)
  case ARGV.fetch(0)
  when 'proxy'
    if mosdns_mode
      api(endpoint, 'dns_config', {'upstream_dns' => ['127.0.0.1:5335'],
        'upstream_dns_file' => '', 'fallback_dns' => [],
        'upstream_mode' => 'load_balance', 'cache_enabled' => false}, netrc)
      api(endpoint, 'cache_clear', :empty_post, netrc)
      File.unlink(state) if File.file?(state)
      next
    end
    unless File.file?(state)
      current = api(endpoint, 'dns_info', nil, netrc)
      saved = {'upstream_dns' => current.fetch('upstream_dns'),
               'upstream_dns_file' => current.fetch('upstream_dns_file', ''),
               'fallback_dns' => current.fetch('fallback_dns', []),
               'upstream_mode' => current.fetch('upstream_mode', 'load_balance'),
               'cache_enabled' => current.fetch('cache_enabled'),
               'cache_size' => current.fetch('cache_size')}
      File.write(state + '.tmp', JSON.generate(saved))
      File.chmod(0600, state + '.tmp')
      File.rename(state + '.tmp', state)
    end
    api(endpoint, 'dns_config', {'upstream_dns' => ['127.0.0.1:7874'],
                                 'upstream_dns_file' => '', 'fallback_dns' => [],
                                 'upstream_mode' => 'load_balance', 'cache_enabled' => false}, netrc)
    api(endpoint, 'cache_clear', :empty_post, netrc)
  when 'direct'
    # MosDNS keeps domestic DNS working while Mihomo is stopped. Never bypass it.
    if mosdns_mode
      api(endpoint, 'dns_config', {'upstream_dns' => ['127.0.0.1:5335'],
        'upstream_dns_file' => '', 'fallback_dns' => [],
        'upstream_mode' => 'load_balance', 'cache_enabled' => false}, netrc)
      api(endpoint, 'cache_clear', :empty_post, netrc)
      next
    end
    if File.file?(state)
      api(endpoint, 'dns_config', JSON.parse(File.read(state)), netrc)
      api(endpoint, 'cache_clear', :empty_post, netrc)
      File.unlink(state)
    end
  when 'prepare'
    path = ARGV.fetch(1)
    document = Psych.parse_stream(File.read(path))
    # Go emits bare IPv6 strings; Psych otherwise treats leading ':' as a Symbol.
    pending = [document]
    until pending.empty?
      node = pending.shift
      if node.is_a?(Psych::Nodes::Scalar) && node.plain && node.value.start_with?(':')
        node.plain = false
        node.quoted = true
        node.style = Psych::Nodes::Scalar::DOUBLE_QUOTED
      end
      pending.concat(node.children || [])
    end
    config = YAML.safe_load(document.to_yaml, permitted_classes: [Time], aliases: true)
    restore_state = File.file?(state) && ENV['AX6000_CLASH_RUNNING'] != '1'
    if restore_state
      JSON.parse(File.read(state)).each { |key, value| config.fetch('dns')[key] = value }
    end
    if mosdns_mode
      config.fetch('dns').merge!('upstream_dns' => ['127.0.0.1:5335'],
        'upstream_dns_file' => '', 'fallback_dns' => [],
        'upstream_mode' => 'load_balance', 'cache_enabled' => false)
    end
    ipv4_only = File.file?('/etc/sysctl.d/99-ax6000-ipv4-only.conf')
    address = (ipv4_only ? '' : ENV.fetch('AX6000_LAN_IPV6', '')).split('/').first
    if address && address.match?(/\A[fdFD][0-9a-fA-F]*:/)
      left, right = address.split('::', 2)
      fields = left.split(':')
      if right
        tail = right.split(':')
        fields += Array.new(8 - fields.size - tail.size, '0') + tail
      end
      raise 'Invalid LAN IPv6 address' unless fields.size == 8
      config.fetch('dhcp').fetch('dhcpv6')['range_start'] = fields.first(4).join(':') + '::100'
    else
      config.fetch('dhcp').fetch('dhcpv6')['range_start'] = ''
    end
    File.write(path + '.tmp', YAML.dump(config))
    File.chmod(0600, path + '.tmp')
    File.rename(path + '.tmp', path)
    File.unlink(state) if restore_state
  else
    raise 'Usage: adguardhome_dns.rb proxy|direct|prepare CONFIG'
  end
end
