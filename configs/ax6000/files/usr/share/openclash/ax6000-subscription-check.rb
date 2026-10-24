#!/usr/bin/ruby
# Refuse incomplete subscription responses before stopping or replacing a core.
require 'yaml'

def load_subscription(path)
  text = File.read(path, encoding: 'UTF-8').gsub('!<str> ', '!!str ')
  value = YAML.load(text)
  raise TypeError unless value.is_a?(Hash)
  raise TypeError unless (value['proxies'] || []).is_a?(Array)
  raise TypeError unless (value['proxy-providers'] || {}).is_a?(Hash)
  raise TypeError unless (value['proxy-groups'] || []).is_a?(Array)
  value
end

def node_names(value)
  (value['proxies'] || []).map { |proxy| proxy['name'] if proxy.is_a?(Hash) }.compact
end

def populated_groups(value)
  nodes = node_names(value)
  providers = value['proxy-providers'] || {}
  groups = (value['proxy-groups'] || []).select { |group| group.is_a?(Hash) }
  by_name = groups.to_h { |group| [group['name'], group] }
  reachable = lambda do |group, seen|
    name = group['name']
    next false if seen.include?(name)
    next true if (group['use'] || []).any? { |provider| providers.key?(provider) }
    if group['include-all'] || group['include-all-proxies'] || group['include-all-providers']
      next true unless nodes.empty? && providers.empty?
    end
    (group['proxies'] || []).any? do |member|
      nodes.include?(member) ||
        (by_name.key?(member) && reachable.call(by_name[member], seen + [name]))
    end
  end
  groups.select do |group|
    %w[url-test fallback load-balance].include?(group['type']) && reachable.call(group, [])
  end.map { |group| group['name'] }
end

def reject_update(reason)
  warn "[AX6000] Subscription rejected: #{reason}; existing configuration retained."
  exit 1
end

begin
  candidate = load_subscription(ARGV.fetch(0))
  new_nodes = node_names(candidate).size
  new_providers = candidate['proxy-providers'] || {}
  reject_update('no nodes or proxy providers') if new_nodes.zero? && new_providers.empty?

  # The initial download and recovery from an unreadable old file have no baseline.
  current = if ARGV[1] && File.file?(ARGV[1])
              begin
                load_subscription(ARGV[1])
              rescue StandardError
                nil
              end
            end
  if current
    old_nodes = node_names(current).size
    if (current['proxy-providers'] || {}).empty? && new_providers.empty? &&
       old_nodes >= 8 && new_nodes * 4 < old_nodes
      reject_update("node count collapsed from #{old_nodes} to #{new_nodes}")
    end
    candidate_groups = (candidate['proxy-groups'] || []).map { |group| group['name'] }
    old_groups = populated_groups(current) & candidate_groups
    lost_groups = old_groups - populated_groups(candidate)
    if old_groups.size >= 4 && lost_groups.size * 4 >= old_groups.size * 3
      reject_update("#{lost_groups.size}/#{old_groups.size} populated automatic groups lost their nodes")
    end
  end
rescue StandardError => error
  # Parser messages can quote private node credentials; only expose their class.
  reject_update("unable to check candidate (#{error.class})")
end
