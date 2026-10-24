#!/usr/bin/ruby
# Public DNS/rules/performance settings come from AX6000_Router.ini + base YAML.
# OpenClash resets DNS listen and TUN hijacking during runtime generation.
require 'yaml'
path = ARGV.fetch(0)
document = Psych.parse_stream(File.read(path))
# Preserve YAML 1.2 strings that Psych's YAML 1.1 loader otherwise retypes.
pending = [document]
until pending.empty?
  node = pending.shift
  if node.is_a?(Psych::Nodes::Scalar) && node.plain &&
     (node.value.start_with?(':') || node.value == 'off')
    node.plain = false
    node.quoted = true
    node.style = Psych::Nodes::Scalar::DOUBLE_QUOTED
  end
  pending.concat(node.children || [])
end
config = YAML.safe_load(document.to_yaml, permitted_classes: [Time], aliases: true)
# OpenClash may already have read the converter's bare `off` as YAML 1.1 false.
config['find-process-mode'] = 'off' if config['find-process-mode'] == false
dns = config['dns']
dns['listen'] = '127.0.0.1:7874' if dns.is_a?(Hash) && dns['enable']
config['tun']['dns-hijack'] = [] if config['tun'].is_a?(Hash)
File.write(path, YAML.dump(config))
